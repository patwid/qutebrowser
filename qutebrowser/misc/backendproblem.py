# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks run at startup for problems with QtWebEngine and its data."""

import os
import sys
import shutil
import os.path

from qutebrowser.qt.widgets import QMessageBox
from qutebrowser.qt.network import QSslSocket

from qutebrowser.config import config, configfiles
from qutebrowser.utils import usertypes, version, log, standarddir
from qutebrowser.misc import msgbox


class _BackendProblemChecker:

    """Check for various issues with QtWebEngine."""

    def _handle_ssl_support(self) -> None:
        """Check for full SSL availability."""
        if QSslSocket.supportsSsl():
            return

        text = ("Could not initialize QtNetwork SSL support. This only "
                "affects downloads and :adblock-update.")

        log.init.warning(text)

    def _handle_serviceworker_nuking(self) -> None:
        """Nuke the service workers directory if the Qt version changed.

        WORKAROUND for:
        https://bugreports.qt.io/browse/QTBUG-72532
        https://bugreports.qt.io/browse/QTBUG-82105
        https://bugreports.qt.io/browse/QTBUG-93744
        """
        if configfiles.state.qt_version_changed:
            reason = 'Qt version changed'
        elif configfiles.state.qtwe_version_changed:
            reason = 'QtWebEngine version changed'
        elif config.val.qt.workarounds.remove_service_workers:
            reason = 'Explicitly enabled'
        else:
            return

        service_worker_dir = os.path.join(
            standarddir.data(), 'webengine', 'Service Worker')
        bak_dir = service_worker_dir + '-bak'
        if not os.path.exists(service_worker_dir):
            return

        log.init.info(
            f"Removing service workers at {service_worker_dir} (reason: {reason})")

        # Keep one backup around - we're not 100% sure what persistent data
        # could be in there, but this folder can grow to ~300 MB.
        if os.path.exists(bak_dir):
            shutil.rmtree(bak_dir)

        shutil.move(service_worker_dir, bak_dir)

    def _confirm_chromium_version_changes(self) -> None:
        """Ask if there is a Chromium downgrade."""
        versions = version.qtwebengine_versions()
        change = configfiles.state.chromium_version_changed
        webengine_data_dir = os.path.join(standarddir.data(), "webengine")

        if change != configfiles.VersionChange.downgrade:
            return

        text = (
            "Chromium/QtWebEngine downgrade detected:<br>"
            f"You are <b>downgrading to QtWebEngine {versions.webengine}</b>."
            "<br><br>"
            "Data managed by Chromium <b>will be discarded</b> if you continue."
            "<br><br>"
            "This affects page data such as cookies, but not data managed by "
            "qutebrowser, such as your configuration or <tt>:open</tt> history.<br>"
            f"The affected data is in <tt>{webengine_data_dir}</tt>."
        )
        box = msgbox.msgbox(
            parent=None,
            title="QtWebEngine version change",
            text=text,
            icon=QMessageBox.Icon.Warning,
            plain_text=False,
            buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Abort,
        )
        response = box.exec()
        if response != QMessageBox.StandardButton.Ok:
            sys.exit(usertypes.Exit.err_init)

    def check(self) -> None:
        """Run all checks."""
        self._handle_ssl_support()
        self._handle_serviceworker_nuking()
        self._confirm_chromium_version_changes()


def init() -> None:
    """Run all checks."""
    _BackendProblemChecker().check()
