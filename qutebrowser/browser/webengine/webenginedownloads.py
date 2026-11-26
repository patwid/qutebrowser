# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""QtWebEngine specific code for downloads."""

import re
import os.path
import functools
import dataclasses

from qutebrowser.qt.core import pyqtSlot, Qt, QUrl, QObject
from qutebrowser.qt.webenginecore import (QWebEngineDownloadRequest, QWebEnginePage,
                                          QWebEngineProfile)

from qutebrowser.browser import downloads, pdfjs
from qutebrowser.utils import debug, usertypes, message, log, urlutils


# URL schemes which can be downloaded via DownloadManager.get(). For anything
# else, QtWebEngine silently never starts a download.
_DOWNLOADABLE_SCHEMES = ['http', 'https', 'file', 'data']


@dataclasses.dataclass
class _Request:

    """A download started by qutebrowser rather than by a website.

    Attributes:
        url: The URL which was requested.
        private: Whether to download via the private profile.
        target: Where to save the download as downloads.DownloadTarget, or None
                to use the default location or ask the user.
        suggested_fn: The filename to suggest, or None to let QtWebEngine pick.
        prompt_download_directory: Overrides downloads.location.prompt if not
                                   None.
    """

    url: QUrl
    private: bool
    target: downloads._DownloadTarget | None = None
    suggested_fn: str | None = None
    prompt_download_directory: bool | None = None


class DownloadItem(downloads.AbstractDownloadItem):

    """A wrapper over a QWebEngineDownloadRequest.

    Attributes:
        _qt_item: The wrapped item.
        _request: The _Request this download was started with, or None if it
                  was started by a website.
    """

    def __init__(self, qt_item: QWebEngineDownloadRequest,
                 manager: 'DownloadManager',
                 request: _Request | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(manager=manager, parent=manager)
        self._qt_item = qt_item
        self._request = request
        qt_item.receivedBytesChanged.connect(
            lambda: self.stats.on_download_progress(
                qt_item.receivedBytes(),
                qt_item.totalBytes(),
            )
        )
        qt_item.totalBytesChanged.connect(
            lambda: self.stats.on_download_progress(
                qt_item.receivedBytes(),
                qt_item.totalBytes(),
            )
        )
        qt_item.stateChanged.connect(
            self._on_state_changed)

        # Ensure wrapped qt_item is deleted manually when the wrapper object
        # is deleted. See https://github.com/qutebrowser/qutebrowser/issues/3373
        self.destroyed.connect(self._qt_item.deleteLater)

    def _is_page_download(self):
        """Check if this item is a page (i.e. mhtml) download."""
        return (self._qt_item.savePageFormat() !=
                QWebEngineDownloadRequest.SavePageFormat.UnknownSaveFormat)

    @pyqtSlot(QWebEngineDownloadRequest.DownloadState)
    def _on_state_changed(self, state):
        state_name = debug.qenum_key(QWebEngineDownloadRequest, state)
        log.downloads.debug("State for {!r} changed to {}".format(
            self, state_name))

        if state == QWebEngineDownloadRequest.DownloadState.DownloadRequested:
            pass
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInProgress:
            pass
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            log.downloads.debug("Download {} finished".format(self.basename))
            if self._is_page_download():
                # Same logging as QtWebKit mhtml downloads.
                log.downloads.debug("File successfully written.")
            self.successful = True
            self.done = True
            self.finished.emit()
            self.stats.finish()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            self.successful = False
            self.done = True
            self.cancelled.emit()
            self.stats.finish()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            self.successful = False
            reason = self._qt_item.interruptReasonString()
            self._die(reason)
        else:
            raise ValueError("_on_state_changed was called with unknown state "
                             "{}".format(state_name))

    def _do_die(self):
        self._qt_item.receivedBytesChanged.disconnect()
        self._qt_item.totalBytesChanged.disconnect()

        if self._qt_item.state() != QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            self._qt_item.cancel()

    def _do_cancel(self):
        state = self._qt_item.state()
        state_name = debug.qenum_key(QWebEngineDownloadRequest, state)
        assert state not in [QWebEngineDownloadRequest.DownloadState.DownloadCompleted,
                             QWebEngineDownloadRequest.DownloadState.DownloadCancelled], state_name
        self._qt_item.cancel()

    def retry(self):
        if self._request is not None:
            # QtWebEngine doesn't send a new request when resuming e.g. after a
            # server error, so we start from scratch instead.
            assert self.done
            assert not self.successful
            self.remove()
            self.delete()
            self._manager.get_request(dataclasses.replace(
                self._request, suggested_fn=self.basename))
            return

        state = self._qt_item.state()
        if state != QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            log.downloads.warning(
                "Refusing to retry download in state {}".format(
                    debug.qenum_key(QWebEngineDownloadRequest, state)))
            return

        self._qt_item.resume()

    def _get_open_filename(self):
        return self._filename

    def url(self) -> QUrl:
        return self._qt_item.url()

    def origin(self) -> QUrl:
        page = self._qt_item.page()
        return page.url() if page else QUrl()

    def _set_tempfile(self, fileobj):
        fileobj.close()
        self._set_filename(fileobj.name, force_overwrite=True,
                           remember_directory=False)

    def _ensure_can_set_filename(self, filename):
        state = self._qt_item.state()
        if state != QWebEngineDownloadRequest.DownloadState.DownloadRequested:
            state_name = debug.qenum_key(QWebEngineDownloadRequest, state)
            raise ValueError("Trying to set filename {} on {!r} which is "
                             "state {} (not in requested state)!".format(
                                 filename, self, state_name))

    def _ask_confirm_question(self, title, msg, *, custom_yes_action=None):
        yes_action = custom_yes_action or self._after_set_filename
        no_action = functools.partial(self.cancel, remove_data=False)
        question = usertypes.Question()
        question.title = title
        question.text = msg
        question.url = 'file://{}'.format(self._filename)
        question.mode = usertypes.PromptMode.yesno
        question.answered_yes.connect(yes_action)
        question.answered_no.connect(no_action)
        question.cancelled.connect(no_action)
        self.cancelled.connect(question.abort)
        self.error.connect(question.abort)
        message.global_bridge.ask(question, blocking=True)

    def _ask_create_parent_question(self, title, msg,
                                    force_overwrite, remember_directory):
        assert self._filename is not None
        no_action = functools.partial(self.cancel, remove_data=False)
        question = usertypes.Question()
        question.title = title
        question.text = msg
        question.url = 'file://{}'.format(os.path.dirname(self._filename))
        question.mode = usertypes.PromptMode.yesno
        question.answered_yes.connect(lambda:
                                      self._after_create_parent_question(
                                          force_overwrite, remember_directory))
        question.answered_no.connect(no_action)
        question.cancelled.connect(no_action)
        self.cancelled.connect(question.abort)
        self.error.connect(question.abort)
        message.global_bridge.ask(question, blocking=True)

    def _after_set_filename(self):
        assert self._filename is not None

        dirname, basename = os.path.split(self._filename)
        self._qt_item.setDownloadDirectory(dirname)
        self._qt_item.setDownloadFileName(basename)

        self._qt_item.accept()

def _strip_suffix(filename):
    """Convert a path we got from chromium to a suggested filename.

    Chromium thinks we want to download stuff to ~/Download, so even if we
    don't, we get downloads with a suffix like (1) for files existing there.

    We simply strip the suffix off via regex.

    See https://bugreports.qt.io/browse/QTBUG-56978
    """
    suffix_re = re.compile(r"""
      \ ?  # Optional space between filename and suffix
      (
        # Numerical suffix
        \([0-9]+\)
      |
        # ISO-8601 suffix
        # https://cs.chromium.org/chromium/src/base/time/time_to_iso8601.cc
        \ -\ \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}Z
      )
      (?=\.|$)  # Begin of extension, or filename without extension
    """, re.VERBOSE)

    return suffix_re.sub('', filename)


class DownloadManager(downloads.AbstractDownloadManager):

    """Manager for currently running downloads.

    Attributes:
        _mhtml_target: DownloadTarget for the next MHTML download.
        _profiles: The profiles we're installed on, by their private state.
        _requests: Downloads requested via get() which QtWebEngine didn't
                   report back yet, by the page they were requested with.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mhtml_target = None
        self._profiles: dict[bool, QWebEngineProfile] = {}
        self._requests: dict[QWebEnginePage, _Request] = {}

    def install(self, profile):
        """Set up the download manager on a QWebEngineProfile."""
        self._profiles[profile.isOffTheRecord()] = profile
        profile.downloadRequested.connect(self.handle_download,
                                          Qt.ConnectionType.DirectConnection)

    def get(self, url, *, private, target=None, suggested_fn=None,
            prompt_download_directory=None):
        """Start a download of the given URL.

        Args:
            url: The URL to get, as QUrl.
            private: Whether to download via the private profile.
            target: Where to save the download as downloads.DownloadTarget.
            suggested_fn: The filename to use for the file.
            prompt_download_directory: Whether to prompt for a location to
                                       download the file to.
        """
        if not url.isValid():
            urlutils.invalid_url_error(url, "start download")
            return

        if url.scheme() not in _DOWNLOADABLE_SCHEMES:
            message.error(f"Download error: Can't download {url.scheme()}:// URLs")
            return

        self.get_request(_Request(
            url=url,
            private=private,
            target=target,
            suggested_fn=suggested_fn,
            prompt_download_directory=prompt_download_directory,
        ))

    def get_request(self, request):
        """Start a download for the given _Request."""
        log.downloads.debug(f"get: {request.url.toDisplayString()}")
        # QtWebEngine doesn't tell us which QWebEnginePage.download() call a
        # download belongs to, and only gives us the URL after redirects. Thus,
        # we use a separate page per download, so that we can tell them apart
        # (and apart from downloads started by a website) in handle_download.
        #
        # This also means that the download isn't affected by the tab it was
        # started from: There is no referer, and it keeps running when the tab
        # gets closed.
        page = QWebEnginePage(self._profiles[request.private], self)
        self._requests[page] = request
        page.download(request.url)

    def _suggested_filename(self, qt_item, request):
        """Get the filename to suggest for the given download."""
        if request is not None and request.suggested_fn is not None:
            return request.suggested_fn

        suggested_filename = _strip_suffix(qt_item.downloadFileName())
        if (request is not None and
                os.path.splitext(suggested_filename)[0] == 'qwe_download'):
            # QtWebEngine couldn't come up with a name (e.g. for data: URLs),
            # see if we can do better.
            return urlutils.filename_from_url(
                request.url, fallback='qutebrowser-download')
        return suggested_filename

    @pyqtSlot(QWebEngineDownloadRequest)
    def handle_download(self, qt_item):
        """Start a download coming from a QWebEngineProfile."""
        mime_type = qt_item.mimeType()
        url = qt_item.url()

        page = qt_item.page()
        request = self._requests.pop(page, None)
        suggested_filename = self._suggested_filename(qt_item, request)

        # Downloads we were explicitly asked for are never shown via PDF.js.
        use_pdfjs = request is None and pdfjs.should_use_pdfjs(mime_type, url)

        download = DownloadItem(qt_item, manager=self, request=request)
        self._init_item(download, auto_remove=use_pdfjs,
                        suggested_filename=suggested_filename)

        prompt_download_directory = None
        if request is not None:
            # The page needs to stay around as long as the download does.
            download.destroyed.connect(page.deleteLater)
            prompt_download_directory = request.prompt_download_directory
            if request.target is not None:
                download.set_target(request.target)
                return

        if self._mhtml_target is not None:
            download.set_target(self._mhtml_target)
            self._mhtml_target = None
            return
        if use_pdfjs:
            download.set_target(downloads.PDFJSDownloadTarget())
            return

        filename = downloads.immediate_download_path(prompt_download_directory)
        if filename is not None:
            # User doesn't want to be asked, so just use the download_dir
            target = downloads.FileDownloadTarget(filename)
            download.set_target(target)
            return

        if download.cancel_for_origin():
            return

        # Ask the user for a filename - needs to be blocking!
        question = downloads.get_filename_question(
            suggested_filename=suggested_filename, url=qt_item.url(),
            parent=self)
        self._init_filename_question(question, download)
        message.global_bridge.ask(question, blocking=True)
        # The filename is set via the question.answered signal, connected in
        # _init_filename_question.

    def get_mhtml(self, tab, target):
        """Download the given tab as mhtml to the given target."""
        assert tab.backend == usertypes.Backend.QtWebEngine
        assert self._mhtml_target is None, self._mhtml_target
        self._mhtml_target = target
        tab.action.save_page()
