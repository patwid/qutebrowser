# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogs shown when there was a problem with a backend choice."""

import os
import sys
import functools
import html
import enum
import shutil
import os.path
import argparse
import dataclasses
from typing import Any
from collections.abc import Sequence

from qutebrowser.qt.core import Qt
from qutebrowser.qt.widgets import (QDialog, QPushButton, QHBoxLayout, QVBoxLayout, QLabel,
                             QMessageBox, QWidget)
from qutebrowser.qt.network import QSslSocket

from qutebrowser.config import config, configfiles
from qutebrowser.utils import usertypes, version, log, utils, standarddir
from qutebrowser.misc import objects, msgbox, savemanager, quitter


class _Result(enum.IntEnum):

    """The result code returned by the backend problem dialog."""

    quit = QDialog.DialogCode.Accepted + 1
    restart = QDialog.DialogCode.Accepted + 2


@dataclasses.dataclass
class _Button:

    """A button passed to BackendProblemDialog."""

    text: str
    setting: str
    value: Any
    default: bool = False


def _error_text(
    because: str,
    text: str,
    backend: usertypes.Backend,
) -> str:
    """Get an error text for the given information."""
    text = (f"<b>Failed to start with the {backend.name} backend!</b>"
            f"<p>qutebrowser tried to start with the {backend.name} backend but "
            f"failed because {because}.</p>{text}")
    return text


class _Dialog(QDialog):

    """A dialog which gets shown if there are issues with the backend."""

    def __init__(self, *, because: str,
                 text: str,
                 backend: usertypes.Backend,
                 buttons: Sequence[_Button] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        vbox = QVBoxLayout(self)

        text = _error_text(because, text, backend)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        vbox.addWidget(label)

        hbox = QHBoxLayout()
        buttons = [] if buttons is None else buttons

        quit_button = QPushButton("Quit")
        quit_button.clicked.connect(lambda: self.done(_Result.quit))
        hbox.addWidget(quit_button)

        for button in buttons:
            btn = QPushButton(button.text)
            btn.setDefault(button.default)
            btn.clicked.connect(functools.partial(
                self._change_setting, button.setting, button.value))
            hbox.addWidget(btn)

        vbox.addLayout(hbox)

    def _change_setting(self, setting: str, value: str) -> None:
        """Change the given setting and restart."""
        config.instance.set_obj(setting, value, save_yaml=True)
        self.done(_Result.restart)


class _BackendProblemChecker:

    """Check for various backend-specific issues."""

    def __init__(self, *,
                 no_err_windows: bool,
                 save_manager: savemanager.SaveManager) -> None:
        self._save_manager = save_manager
        self._no_err_windows = no_err_windows

    def _show_dialog(self, *args: Any, **kwargs: Any) -> None:
        """Show a dialog for a backend problem."""
        if self._no_err_windows:
            text = _error_text(*args, **kwargs)
            log.init.error(text)
            sys.exit(usertypes.Exit.err_init)

        dialog = _Dialog(*args, **kwargs)

        status = dialog.exec()
        self._save_manager.save_all(is_exit=True)

        if status in [_Result.quit, QDialog.DialogCode.Rejected]:
            pass
        elif status == _Result.restart:
            quitter.instance.restart()
        else:
            raise utils.Unreachable(status)

        sys.exit(usertypes.Exit.err_init)

    def _handle_ssl_support(self) -> None:
        """Check for full SSL availability."""
        if QSslSocket.supportsSsl():
            return

        text = ("Could not initialize QtNetwork SSL support. This only "
                "affects downloads and :adblock-update.")

        log.init.warning(text)

    def _check_backend_modules(self) -> None:
        """Check for the modules needed for QtWebEngine."""
        try:
            # pylint: disable-next=unused-import
            from qutebrowser.qt import webenginecore, webenginewidgets
        except (ImportError, ValueError) as e:
            error = str(e)
            assert error
        else:
            return

        self._show_dialog(
            backend=usertypes.Backend.QtWebEngine,
            because="QtWebEngine could not be imported",
            text="<p><b>The error encountered was:</b><br/>{}</p>".format(
                html.escape(error))
        )

        raise utils.Unreachable

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
        """Ask if there are Chromium downgrades or a Qt 5 -> 6 upgrade."""
        versions = version.qtwebengine_versions(avoid_init=True)
        change = configfiles.state.chromium_version_changed
        webengine_data_dir = os.path.join(standarddir.data(), "webengine")

        if change == configfiles.VersionChange.major:
            icon = QMessageBox.Icon.Information
            text = (
                "Chromium/QtWebEngine upgrade detected:<br>"
                f"You are <b>upgrading to QtWebEngine {versions.webengine}</b> but "
                "used Qt 5 for the last qutebrowser launch.<br><br>"
                "Data managed by Chromium will be upgraded. This is a <b>one-way "
                "operation:</b> If you open qutebrowser with Qt 5 again later, any "
                "Chromium data will be <b>invalid and discarded</b>.<br><br>"
                "This affects page data such as cookies, but not data managed by "
                "qutebrowser, such as your configuration or <tt>:open</tt> history.<br>"
                f"The affected data is in <tt>{webengine_data_dir}</tt>."
            )
        elif change == configfiles.VersionChange.downgrade:
            icon = QMessageBox.Icon.Warning
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
        else:
            return

        box = msgbox.msgbox(
            parent=None,
            title="QtWebEngine version change",
            text=text,
            icon=icon,
            plain_text=False,
            buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Abort,
        )
        response = box.exec()
        if response != QMessageBox.StandardButton.Ok:
            sys.exit(usertypes.Exit.err_init)

    def _force_wayland_hardware_acceleration(self) -> None:
        """Set environment variable so hardware acceleration works on Wayland.

        Set EGL_PLATFORM=wayland to force ANGLE to obtain EGL display connection
        for wayland platform. Otherwise, the display connection for
        EGL_DEFAULT_DISPLAY may belong to a platform which Nvidia's EGL driver
        doesn't support. In case of unsupported platform, EGL may fallback to
        Mesa software renderer (LLVMPipe) disabling hardware acceleration in
        Chromium.

        Equivalent to:
        https://codereview.qt-project.org/c/qt/qtwebengine/+/663568
        """
        if objects.qapp.platformName() != 'wayland':
            return

        versions = version.qtwebengine_versions(avoid_init=True)
        if versions.webengine >= utils.VersionNumber(6, 10):
            # Qt workaround is active
            return

        egl_platform_var = "EGL_PLATFORM"
        egl_platform = os.environ.get(egl_platform_var)
        if not egl_platform:
            os.environ[egl_platform_var] = "wayland"
        elif egl_platform != "wayland":
            log.init.warning(
                f"{egl_platform_var} environment variable is set to {egl_platform!r}. "
                "This may break hardware rendering on Wayland."
            )

    def _fix_wayland_amd_gbm(self) -> None:
        """Force GBM to off with Qt 6.11.0 and AMD GPUs on Wayland."""
        if objects.qapp.platformName() != "wayland":
            return

        versions = version.qtwebengine_versions(avoid_init=True)
        if versions.webengine != utils.VersionNumber(6, 11):
            # Older versions are not affected; assuming fixed with Qt 6.11.1
            return

        opengl_info = version.opengl_info()
        if opengl_info is None or opengl_info.vendor != "AMD":
            return

        env_var = "QTWEBENGINE_FORCE_USE_GBM"
        env_value = os.environ.get(env_var, "0")
        if env_value != "0":
            log.init.warning(
                f"{env_var} environment variable is set to {env_value!r}. "
                "This may cause issues with AMD GPUs on Wayland with Qt 6.11.0."
            )
            return

        log.init.warning(
            "Disabling GBM support to avoid issues with AMD GPUs on Wayland with "
            "Qt 6.11.0")
        os.environ[env_var] = "0"

    def _assert_backend(self, backend: usertypes.Backend) -> None:
        assert objects.backend == backend, objects.backend

    def check(self) -> None:
        """Run all checks."""
        self._assert_backend(usertypes.Backend.QtWebEngine)
        self._check_backend_modules()
        self._handle_ssl_support()
        self._handle_serviceworker_nuking()
        self._force_wayland_hardware_acceleration()
        self._fix_wayland_amd_gbm()
        self._confirm_chromium_version_changes()


def init(*, args: argparse.Namespace,
         save_manager: savemanager.SaveManager) -> None:
    """Run all checks."""
    checker = _BackendProblemChecker(no_err_windows=args.no_err_windows,
                                     save_manager=save_manager)
    checker.check()
