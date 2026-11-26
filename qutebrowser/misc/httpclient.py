# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An HTTP client based on QNetworkAccessManager."""

import io
import functools
import urllib.parse
from typing import IO
from collections.abc import MutableMapping

from qutebrowser.qt.core import (pyqtSignal, pyqtSlot, QObject, QTimer, QUrl,
                                 QCoreApplication)
from qutebrowser.qt.network import (QNetworkAccessManager, QNetworkRequest,
                             QNetworkReply)

from qutebrowser.config import websettings
from qutebrowser.utils import qtlog, usertypes, log, message


class HTTPRequest(QNetworkRequest):
    """A QNetworkRequest that follows (secure) redirects by default."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                          QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)


class HTTPClient(QObject):

    """An HTTP client based on QNetworkAccessManager.

    Intended for APIs, automatically decodes data.

    Attributes:
        _nam: The QNetworkAccessManager used.
        _timers: A {QNetworkReply: QTimer} dict.

    Signals:
        success: Emitted when the operation succeeded.
                 arg: The received data.
        error: Emitted when the request failed.
               arg: The error message, as string.
    """

    success = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        with qtlog.disable_qt_msghandler():
            # WORKAROUND for a hang when messages are printed, see our
            # NetworkAccessManager subclass for details.
            self._nam = QNetworkAccessManager(self)
        self._timers: MutableMapping[QNetworkReply, QTimer] = {}

    def post(self, url, data=None):
        """Create a new POST request.

        Args:
            url: The URL to post to, as QUrl.
            data: A dict of data to send.
        """
        if data is None:
            data = {}
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        request = HTTPRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          'application/x-www-form-urlencoded;charset=utf-8')
        reply = self._nam.post(request, encoded_data)
        self._handle_reply(reply)

    def get(self, url):
        """Create a new GET request.

        Emits success/error when done.

        Args:
            url: The URL to access, as QUrl.
        """
        request = HTTPRequest(url)
        reply = self._nam.get(request)
        self._handle_reply(reply)

    def _handle_reply(self, reply):
        """Handle a new QNetworkReply."""
        if reply.isFinished():
            self.on_reply_finished(reply)
        else:
            timer = usertypes.Timer(self)
            timer.setInterval(10000)
            timer.timeout.connect(reply.abort)
            timer.start()
            self._timers[reply] = timer
            reply.finished.connect(functools.partial(
                self.on_reply_finished, reply))

    def on_reply_finished(self, reply):
        """Read the data and finish when the reply finished.

        Args:
            reply: The QNetworkReply which finished.
        """
        timer = self._timers.pop(reply)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.error.emit(reply.errorString())
            return
        try:
            data = bytes(reply.readAll()).decode('utf-8')
        except UnicodeDecodeError:
            self.error.emit("Invalid UTF-8 data received in reply!")
            return
        self.success.emit(data)


class Fetch(QObject):

    """A GET request reading some data into memory.

    Used for things qutebrowser fetches for itself (e.g. adblock lists), which
    are neither shown in the download bar nor saved to disk.

    Attributes:
        url: The requested URL.
        successful: Whether the data was fetched successfully. Only meaningful
                    after `finished` was emitted.
        error_msg: The error message if the request failed, None otherwise.
        fileobj: A file-like object with the fetched data.
        _reply: The underlying QNetworkReply, None once finished.

    Signals:
        finished: Emitted when the request is done, successfully or not.
    """

    finished = pyqtSignal()

    def __init__(self, reply: QNetworkReply, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = reply.request().url()
        self.successful = False
        self.error_msg: str | None = None
        fileobj = io.BytesIO()
        fileobj.name = 'temporary: ' + self.url.host()
        self.fileobj: IO[bytes] = fileobj
        self._reply: QNetworkReply | None = reply

        if reply.isFinished():
            QTimer.singleShot(0, self._on_reply_finished)
        else:
            reply.finished.connect(self._on_reply_finished)

    @pyqtSlot()
    def _on_reply_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None

        if reply.error() == QNetworkReply.NetworkError.NoError:
            self.fileobj.write(reply.readAll().data())
            self.successful = True
        else:
            self.error_msg = reply.errorString()
            log.downloads.debug(
                f"Fetching {self.url.toDisplayString()} failed: {self.error_msg}")
            message.error(f"Download error: {self.error_msg}")

        reply.deleteLater()
        _running_fetches.discard(self)
        self.finished.emit()


# How long a fetch may go without any data being transferred, in ms.
_FETCH_TIMEOUT = 30000
_fetch_nam: QNetworkAccessManager | None = None
# Keeps Fetch objects alive until they are finished.
_running_fetches: set[Fetch] = set()


def fetch(url: QUrl) -> Fetch:
    """Fetch the given URL into memory, using the configured user agent.

    Args:
        url: The URL to get, as QUrl.

    Return:
        A Fetch object, emitting `finished` once the request is done.
    """
    global _fetch_nam
    if _fetch_nam is None:
        with qtlog.disable_qt_msghandler():
            # WORKAROUND for a hang when messages are printed, see our
            # NetworkAccessManager subclass for details.
            _fetch_nam = QNetworkAccessManager(QCoreApplication.instance())

    request = HTTPRequest(url)
    request.setTransferTimeout(_FETCH_TIMEOUT)
    request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                      websettings.user_agent(url))

    reply = _fetch_nam.get(request)
    assert reply is not None
    download = Fetch(reply)
    _running_fetches.add(download)
    return download
