# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Handlers for crashes and OS signals."""

import os
import os.path
import logging
import sys
import fcntl
import bdb
import pdb  # noqa: T002
import types
import signal
import functools
import threading
import faulthandler
from typing import TYPE_CHECKING, cast
from collections.abc import Callable, MutableMapping

from qutebrowser.qt.core import (pyqtSlot, qInstallMessageHandler, QObject,
                          QSocketNotifier, QTimer, QUrl)
from qutebrowser.qt.widgets import QApplication

from qutebrowser.config import configfiles, configexc
from qutebrowser.misc import earlyinit, ipc, objects
from qutebrowser.utils import usertypes, standarddir, log, objreg, message
from qutebrowser.qt import sip
if TYPE_CHECKING:
    from qutebrowser.misc import quitter


crash_handler = cast('CrashHandler', None)


class CrashHandler(QObject):

    """Handler for crashes and exceptions.

    Attributes:
        _app: The QApplication instance.
        _quitter: The Quitter instance.
        _crash_log_file: The file handle for the faulthandler crash log.
        is_crashing: Used by mainwindow.py to skip confirm questions on
                     crashes.
    """

    def __init__(self, *, app, quitter, parent=None):
        super().__init__(parent)
        self._app = app
        self._quitter = quitter
        self._crash_log_file = None
        self.is_crashing = False

    def activate(self):
        """Activate the exception hook."""
        sys.excepthook = self.exception_hook

    def init_faulthandler(self):
        """Log a segfault from a previous run and set up faulthandler."""
        logname = os.path.join(standarddir.data(), 'crash.log')
        try:
            if os.path.exists(logname):
                with open(logname, 'r', encoding='ascii') as f:
                    data = f.read()
                os.remove(logname)
                if data:
                    log.init.error(
                        "qutebrowser crashed the last time it was run:\n" + data)
        except (OSError, UnicodeDecodeError):
            log.init.exception("Error while handling crash log file!")
        self._init_crashlogfile()

    def _recover_pages(self):
        """Try to recover all open pages.

        Called from exception_hook, so as forgiving as possible.

        Return:
            A list containing a list for each window, which in turn contain the
            opened URLs.
        """
        pages = []
        for win_id in objreg.window_registry:
            win_pages = []
            tabbed_browser = objreg.get('tabbed-browser', scope='window',
                                        window=win_id)
            for tab in tabbed_browser.widgets():
                try:
                    urlstr = tab.url().toString(
                        QUrl.UrlFormattingOption.RemovePassword | QUrl.ComponentFormattingOption.FullyEncoded)
                    if urlstr:
                        win_pages.append(urlstr)
                except Exception:
                    log.destroy.exception("Error while recovering tab")
            pages.append(win_pages)
        return pages

    def _init_crashlogfile(self):
        """Start a new logfile and redirect faulthandler to it."""
        logname = os.path.join(standarddir.data(), 'crash.log')
        try:
            # pylint: disable=consider-using-with
            self._crash_log_file = open(logname, 'w', encoding='ascii')
        except OSError:
            log.init.exception("Error while opening crash log file!")
        else:
            earlyinit.init_faulthandler(self._crash_log_file)

    @pyqtSlot()
    def shutdown(self):
        self.destroy_crashlogfile()

    def destroy_crashlogfile(self):
        """Clean up the crash log file and delete it."""
        if self._crash_log_file is None:
            return
        # We use sys.__stderr__ instead of sys.stderr here so this will still
        # work when sys.stderr got replaced, e.g. by "Python Tools for Visual
        # Studio".
        if sys.__stderr__ is not None:
            faulthandler.enable(sys.__stderr__)
        else:
            faulthandler.disable()
        try:
            self._crash_log_file.close()
            os.remove(self._crash_log_file.name)
        except OSError:
            log.destroy.exception("Could not remove crash log!")

    def _handle_early_exits(self, exc):
        """Handle some special cases for the exception hook.

        Return value:
            True: Exception hook should be aborted.
            False: Continue handling exception.
        """
        exctype, _excvalue, tb = exc

        if not self._quitter.quit_status['crash']:
            log.misc.error("ARGH, there was an exception while already "
                           "handling one:", exc_info=exc)
            return True

        log.misc.error("Uncaught exception", exc_info=exc)

        is_ignored_exception = (exctype is bdb.BdbQuit or
                                not issubclass(exctype, Exception))

        if 'pdb-postmortem' in objects.debug_flags:
            if tb is None:
                pdb.set_trace()  # noqa: T100 pylint: disable=forgotten-debug-statement
            else:
                pdb.post_mortem(tb)

        if is_ignored_exception or 'pdb-postmortem' in objects.debug_flags:
            # pdb exit, KeyboardInterrupt, ...
            sys.exit(usertypes.Exit.exception)

        if threading.current_thread() != threading.main_thread():
            log.misc.error("Ignoring exception outside of main thread...")
            return True

        return False

    def exception_hook(self, exctype, excvalue, tb):
        """Handle uncaught python exceptions.

        The exception is logged above, here we print the open pages to stderr
        so they are not lost, and exit.
        """
        exc = (exctype, excvalue, tb)

        if self._handle_early_exits(exc):
            return

        self._quitter.quit_status['crash'] = False

        try:
            pages = self._recover_pages()
        except Exception:
            log.destroy.exception("Error while recovering pages")
            pages = []

        if ipc.server is not None:
            try:
                ipc.server.ignored = True
            except Exception:
                log.destroy.exception("Error while ignoring ipc")

        try:
            self._app.lastWindowClosed.disconnect(
                self._quitter.on_last_window_closed)
        except TypeError:
            log.destroy.exception("Error while preventing shutdown")

        self.is_crashing = True

        self._app.closeAllWindows()
        print("\n---- Open pages ----", file=sys.stderr)
        print('\n\n'.join('\n'.join(e) for e in pages), file=sys.stderr)

        # We only do the most needed shutdown here, and then leave without
        # running any Python or Qt cleanup: Tearing down the application from
        # inside the exception hook segfaults.
        qInstallMessageHandler(None)
        self.destroy_crashlogfile()
        logging.shutdown()
        for stream in [sys.stdout, sys.stderr]:
            try:
                stream.flush()
            except (OSError, ValueError, AttributeError):
                pass
        os._exit(usertypes.Exit.exception)


class SignalHandler(QObject):

    """Handler responsible for handling OS signals (SIGINT, SIGTERM, etc.).

    Attributes:
        _app: The QApplication instance.
        _quitter: The Quitter instance.
        _activated: Whether activate() was called.
        _notifier: A QSocketNotifier used for signals on Unix.
        _orig_handlers: A {signal: handler} dict of original signal handlers.
        _orig_wakeup_fd: The original wakeup filedescriptor.
    """

    def __init__(self, *, app, quitter, parent=None):
        super().__init__(parent)
        self._app = app
        self._quitter = quitter
        self._notifier = None
        self._orig_handlers: MutableMapping[int, 'signal._HANDLER'] = {}
        self._activated = False
        self._orig_wakeup_fd: int | None = None

        self._handlers: dict[
            signal.Signals, Callable[[int, types.FrameType | None], None]
        ] = {
            signal.SIGINT: self.interrupt,
            signal.SIGTERM: self.interrupt,
        }
        platform_dependant_handlers = {
            "SIGHUP": self.reload_config,
        }
        for sig_str, handler in platform_dependant_handlers.items():
            try:
                self._handlers[signal.Signals[sig_str]] = handler
            except KeyError:
                pass

    def activate(self):
        """Set up signal handlers.

        This uses a QSocketNotifier with os.set_wakeup_fd to get notified.
        """
        for sig, handler in self._handlers.items():
            self._orig_handlers[sig] = signal.signal(sig, handler)

        read_fd, write_fd = os.pipe()
        for fd in [read_fd, write_fd]:
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._notifier = QSocketNotifier(cast(sip.voidptr, read_fd),
                                         QSocketNotifier.Type.Read,
                                         self)
        self._notifier.activated.connect(self.handle_signal_wakeup)
        self._orig_wakeup_fd = signal.set_wakeup_fd(write_fd)
        self._activated = True

    def deactivate(self):
        """Deactivate all signal handlers."""
        if not self._activated:
            return
        if self._notifier is not None:
            assert self._orig_wakeup_fd is not None
            self._notifier.setEnabled(False)
            rfd = self._notifier.socket()
            wfd = signal.set_wakeup_fd(self._orig_wakeup_fd)
            os.close(int(rfd))
            os.close(wfd)
        for sig, handler in self._orig_handlers.items():
            signal.signal(sig, handler)
        self._activated = False

    @pyqtSlot()
    def handle_signal_wakeup(self):
        """Handle a newly arrived signal.

        This gets called via self._notifier when there's a signal.

        Python will get control here, so the signal will get handled.
        """
        assert self._notifier is not None
        log.destroy.debug("Handling signal wakeup!")
        self._notifier.setEnabled(False)
        read_fd = self._notifier.socket()
        try:
            os.read(int(read_fd), 1)
        except OSError:
            log.destroy.exception("Failed to read wakeup fd.")
        self._notifier.setEnabled(True)

    def _log_later(self, *lines):
        """Log the given text line-wise with a QTimer."""
        for line in lines:
            QTimer.singleShot(0, functools.partial(log.destroy.info, line))

    def interrupt(self, signum, _frame):
        """Handler for signals to gracefully shutdown (SIGINT/SIGTERM).

        This calls shutdown and remaps the signal to call
        interrupt_forcefully the next time.
        """
        signal.signal(signal.SIGINT, self.interrupt_forcefully)
        signal.signal(signal.SIGTERM, self.interrupt_forcefully)
        # Signals can arrive anywhere, so we do this in the main thread
        self._log_later("SIGINT/SIGTERM received, shutting down!",
                        "Do the same again to forcefully quit.")
        QTimer.singleShot(0, functools.partial(
            self._quitter.shutdown, 128 + signum))

    def interrupt_forcefully(self, signum, _frame):
        """Interrupt forcefully on the second SIGINT/SIGTERM request.

        This skips our shutdown routine and calls QApplication:exit instead.
        It then remaps the signals to call self.interrupt_really_forcefully the
        next time.
        """
        signal.signal(signal.SIGINT, self.interrupt_really_forcefully)
        signal.signal(signal.SIGTERM, self.interrupt_really_forcefully)
        # Signals can arrive anywhere, so we do this in the main thread
        self._log_later("Forceful quit requested, goodbye cruel world!",
                        "Do the same again to quit with even more force.")
        QTimer.singleShot(0, functools.partial(self._app.exit, 128 + signum))

    def interrupt_really_forcefully(self, signum, _frame):
        """Interrupt with even more force on the third SIGINT/SIGTERM request.

        This doesn't run *any* Qt cleanup and simply exits via Python.
        It will most likely lead to a segfault.
        """
        print("WHY ARE YOU DOING THIS TO ME? :(")
        sys.exit(128 + signum)

    def reload_config(self, _signum, _frame):
        """Reload the config."""
        log.signals.info("SIGHUP received, reloading config.")
        filename = standarddir.config_py()
        try:
            configfiles.read_config_py(filename)
        except configexc.ConfigFileErrors as e:
            message.error(str(e))


def init(q_app: QApplication, quitter: 'quitter.Quitter') -> None:
    """Initialize crash/signal handlers."""
    global crash_handler
    crash_handler = CrashHandler(app=q_app, quitter=quitter, parent=q_app)
    crash_handler.activate()
    quitter.shutting_down.connect(crash_handler.shutdown)

    signal_handler = SignalHandler(app=q_app, quitter=quitter, parent=q_app)
    signal_handler.activate()
    quitter.shutting_down.connect(signal_handler.deactivate)
