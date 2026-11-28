# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""QtWebEngine specific code for downloads."""

import re
import html
import os.path
import functools
import dataclasses

from qutebrowser.qt.core import pyqtSignal, pyqtSlot, Qt, QUrl, QObject
from qutebrowser.qt.network import QAuthenticator
from qutebrowser.qt.webenginecore import (QWebEngineDownloadRequest, QWebEnginePage,
                                          QWebEngineProfile, QWebEngineSettings,
                                          QWebEngineCertificateError)

from qutebrowser.browser import downloads, shared
from qutebrowser.browser.webengine import certificateerror
from qutebrowser.utils import debug, usertypes, message, log, urlutils, objreg


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
        user: The username to authenticate with, or None.
        password: The password to authenticate with, or None.
        netrc_used: Whether the netrc file was already consulted.
        certificate_checked: Whether we already checked for a certificate
                             error of the host.
    """

    url: QUrl
    private: bool
    target: downloads._DownloadTarget | None = None
    suggested_fn: str | None = None
    prompt_download_directory: bool | None = None
    user: str | None = None
    password: str | None = None
    netrc_used: bool = False
    certificate_checked: bool = False

    def url_with_credentials(self) -> QUrl:
        """Get the URL to request, including the credentials (if any)."""
        url = QUrl(self.url)
        if self.user is not None:
            url.setUserName(self.user)
            url.setPassword(self.password)
        return url


class _CertificateCheck(QObject):

    """Handle a certificate error of the host a failed download came from.

    QtWebEngine doesn't report certificate errors for downloads started via
    QWebEnginePage.download(), they just fail. However, once a page of the
    same host was loaded despite its certificate error, downloads from it work
    too. Thus, we load the start page of the host in a page of our own, only
    to get its certificate error.

    Signals:
        accepted: Emitted when a certificate error was accepted and the page
                  was loaded.
    """

    accepted = pyqtSignal()

    def __init__(self, url: QUrl, profile: QWebEngineProfile, *,
                 abort_on: list, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self._abort_on = abort_on
        self._accepted = False
        self._page = QWebEnginePage(profile, self)
        settings = self._page.settings()
        for attribute in [QWebEngineSettings.WebAttribute.JavascriptEnabled,
                          QWebEngineSettings.WebAttribute.AutoLoadImages]:
            settings.setAttribute(attribute, False)
        self._page.certificateError.connect(self._on_certificate_error)
        self._page.urlChanged.connect(self._on_url_changed)
        self._page.loadFinished.connect(self._on_load_finished)

        probe_url = QUrl()
        probe_url.setScheme(url.scheme())
        probe_url.setHost(url.host())
        probe_url.setPort(url.port())
        probe_url.setPath('/')
        log.downloads.debug(
            f"Checking for certificate errors: {probe_url.toDisplayString()}")
        self._page.load(probe_url)

    @pyqtSlot(QWebEngineCertificateError)
    def _on_certificate_error(self, qt_error):
        error = certificateerror.CertificateErrorWrapper(qt_error)
        if not error.is_overridable():
            log.network.error(f"Non-overridable certificate error: {error}")
            return
        shared.handle_certificate_error(
            request_url=self._url,
            first_party_url=QUrl(),
            error=error,
            abort_on=self._abort_on,
        )
        self._accepted = error.certificate_was_accepted()

    @pyqtSlot()
    def _on_url_changed(self):
        if not self._accepted:
            # The page loads without a certificate error (or we rejected
            # it), so there is nothing to do for us.
            self._page.triggerAction(QWebEnginePage.WebAction.Stop)
            self.deleteLater()

    @pyqtSlot(bool)
    def _on_load_finished(self, ok):
        if self._accepted and ok:
            self.accepted.emit()
        self.deleteLater()


class DownloadItem(downloads.AbstractDownloadItem):

    """A wrapper over a QWebEngineDownloadRequest.

    Attributes:
        _qt_item: The wrapped item.
        _request: The _Request this download was started with, or None if it
                  was started by a website.
        _target: The target this download is saved to, or None if not set yet.
    """

    def __init__(self, qt_item: QWebEngineDownloadRequest,
                 manager: 'DownloadManager',
                 request: _Request | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(manager=manager, parent=manager)
        self._qt_item = qt_item
        self._request = request
        self._target: downloads._DownloadTarget | None = None
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
            needs_auth = self._request is not None and (
                self._qt_item.interruptReason() ==
                QWebEngineDownloadRequest.DownloadInterruptReason.ServerUnauthorized)
            if needs_auth and self._retry_with_netrc():
                return
            needs_certificate_check = (
                self._request is not None and
                not self._request.certificate_checked and
                self._request.url.scheme() == 'https' and
                self._qt_item.interruptReason() ==
                QWebEngineDownloadRequest.DownloadInterruptReason.NetworkFailed)
            self._die(reason)
            if needs_auth:
                self._ask_for_credentials()
            elif needs_certificate_check:
                self._check_certificate()
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

    def set_target(self, target):
        self._target = target
        super().set_target(target)

    def _restart(self, **changes):
        """Replace this download by a new one for a changed request."""
        assert self._request is not None
        assert not self.successful
        if not self._dead:
            self._dead = True
            self._do_die()
            self.stats.finish()
            self.done = True
        self.remove()
        self.delete()
        self._manager.get_request(dataclasses.replace(self._request, **changes))

    def _retry_with_netrc(self):
        """Retry an unauthorized download with credentials from netrc.

        QtWebEngine doesn't ask for credentials for downloads started via
        QWebEnginePage.download(), so we pass them as part of the URL instead.

        Return:
            True if the download was restarted, False otherwise.
        """
        assert self._request is not None
        if self._request.netrc_used:
            return False

        authenticator = QAuthenticator()
        if not shared.netrc_authentication(self._request.url, authenticator):
            return False

        self._restart(
            user=authenticator.user(),
            password=authenticator.password(),
            netrc_used=True,
            target=self._target or self._request.target,
            suggested_fn=self.basename,
        )
        return True

    def _ask_for_credentials(self):
        """Ask for credentials for an unauthorized download and retry it."""
        assert self._request is not None
        url = self._request.url
        message.ask_async(
            title="Authentication required",
            text="<b>{}</b> needs authentication".format(
                html.escape(url.toDisplayString())),
            mode=usertypes.PromptMode.user_pwd,
            handler=self._on_credentials_entered,
            abort_on=[self.remove_requested],
            url=url.toString(QUrl.UrlFormattingOption.RemovePassword |
                             QUrl.ComponentFormattingOption.FullyEncoded),
        )

    def _on_credentials_entered(self, answer):
        self._restart(
            user=answer.user,
            password=answer.password,
            netrc_used=True,
            target=self._target or self._request.target,
            suggested_fn=self.basename,
        )

    def _check_certificate(self):
        """Check if a failed download was due to a certificate error.

        If so, and the user (or the config) accepts the certificate, the
        download is started again.
        """
        assert self._request is not None
        check = _CertificateCheck(
            self._request.url,
            self._manager.profile(private=self._request.private),
            abort_on=[self.remove_requested],
            parent=self._manager)
        check.accepted.connect(self._on_certificate_accepted)

    @pyqtSlot()
    def _on_certificate_accepted(self):
        self._restart(
            certificate_checked=True,
            target=self._target or self._request.target,
            suggested_fn=self.basename,
        )

    def retry(self):
        if self._request is not None:
            # QtWebEngine doesn't send a new request when resuming e.g. after a
            # server error, so we start from scratch instead.
            assert self.done
            self._restart(suggested_fn=self.basename)
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
        url = self._qt_item.url()
        if self._request is not None and self._request.user is not None:
            # Don't show credentials we added ourselves.
            url.setUserInfo(None)
        return url

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

    @pyqtSlot(str)
    def _on_pdf_viewer_requested(self, filename):
        tabbed_browser = objreg.get('tabbed-browser', scope='window',
                                    window='last-focused')
        tab = tabbed_browser.tabopen(background=False)
        # The viewer is only turned on for this tab, independently of the
        # content.pdf_viewer setting.
        tab.settings.force_pdf_viewer()
        tab.load_url(QUrl.fromLocalFile(filename))

    def profile(self, *, private):
        """Get the profile used for (private or normal) downloads."""
        return self._profiles[private]

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
        page.download(request.url_with_credentials())

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
        page = qt_item.page()
        request = self._requests.pop(page, None)
        suggested_filename = self._suggested_filename(qt_item, request)

        download = DownloadItem(qt_item, manager=self, request=request)
        self._init_item(download, suggested_filename=suggested_filename)

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
        assert self._mhtml_target is None, self._mhtml_target
        self._mhtml_target = target
        tab.action.save_page()
