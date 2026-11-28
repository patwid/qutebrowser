# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hiding page elements matched by cosmetic rules of the adblock lists.

The work is split between javascript/cosmetic.js running in the page, and the
adblock engine in components/braveadblock.py. CosmeticBridge connects the two
via a QWebChannel, which is only exposed to our own (isolated) JavaScript
world, not to the page.
"""

import json
import functools

from qutebrowser.qt.core import pyqtSlot, QObject, QUrl, QFile, QIODevice
from qutebrowser.qt.webchannel import QWebChannel
from qutebrowser.qt.webenginecore import QWebEnginePage, QWebEngineScript

from qutebrowser.components import braveadblock
from qutebrowser.utils import log, resources, javascript

# Limits for what we accept from a page, as class names and IDs are entirely
# up to it.
_MAX_NAMES = 10000
_MAX_NAME_LENGTH = 256


@functools.cache
def js_code() -> str:
    """Get the JavaScript to inject into pages."""
    qwebchannel_js = QFile(':/qtwebchannel/qwebchannel.js')
    if not qwebchannel_js.open(QIODevice.OpenModeFlag.ReadOnly):
        raise OSError(f"Failed to read qwebchannel.js: {qwebchannel_js.errorString()}")
    try:
        qwebchannel_code = bytes(qwebchannel_js.readAll()).decode('utf-8')
    finally:
        qwebchannel_js.close()

    return javascript.wrap_global(
        'cosmetic',
        qwebchannel_code,
        resources.read_file('javascript/cosmetic.js'),
    )


def _names(value: object) -> list[str]:
    """Validate a list of class names or IDs coming from a page."""
    if not isinstance(value, list):
        return []
    return [name for name in value[:_MAX_NAMES]
            if isinstance(name, str) and 0 < len(name) <= _MAX_NAME_LENGTH]


class CosmeticBridge(QObject):

    """The object javascript/cosmetic.js talks to, one per page.

    Attributes:
        _exceptions: Selectors which must not be hidden on the current page.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._exceptions: set[str] = set()
        self._channel = QWebChannel(self)
        self._channel.registerObject('cosmetic', self)

    def install(self, page: QWebEnginePage) -> None:
        """Make this object available to our JavaScript in the given page."""
        page.setWebChannel(
            self._channel, QWebEngineScript.ScriptWorldId.ApplicationWorld)

    @pyqtSlot(str, str, result=str)
    def rules(self, token: str, urlstr: str) -> str:
        """Get the rules applying to a page, as JSON.

        Args:
            token: A token identifying the document asking, which is part of
                   the answer.
            urlstr: The URL of the page.
        """
        self._exceptions = set()
        blocker = braveadblock.ad_blocker
        url = QUrl(urlstr)
        found = None if blocker is None else blocker.cosmetic_resources(url)
        if found is None:
            log.network.debug(
                f"Cosmetic rules disabled for {url.toDisplayString()}")
            return json.dumps({'token': token, 'enabled': False})

        log.network.debug(
            f"Cosmetic rules for {url.toDisplayString()}: "
            f"{len(found.hide_selectors)} hidden, "
            f"{len(found.style_selectors)} styled, "
            f"{len(found.exceptions)} exceptions, generic: {found.generic}")
        self._exceptions = found.exceptions
        return json.dumps({
            'token': token,
            'enabled': True,
            'hide': found.hide_selectors,
            'style': found.style_selectors,
            'generic': found.generic,
        })

    @pyqtSlot(str, result=str)
    def generic_selectors(self, request: str) -> str:
        """Get the selectors to hide for some classes and IDs, as JSON.

        Args:
            request: A JSON object with a "classes" and an "ids" list, and
                     the token of the document asking.
        """
        try:
            data = json.loads(request)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            data = {}

        blocker = braveadblock.ad_blocker
        selectors = [] if blocker is None else blocker.generic_hide_selectors(
            classes=_names(data.get('classes')),
            ids=_names(data.get('ids')),
            exceptions=self._exceptions,
        )
        return json.dumps({'token': data.get('token'), 'selectors': selectors})
