# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.utils.qtlog."""

import dataclasses

import pytest

from qutebrowser import qutebrowser
from qutebrowser.utils import qtlog

from qutebrowser.qt import core as qtcore


class TestQtMessageHandler:

    @dataclasses.dataclass
    class Context:

        """Fake QMessageLogContext."""

        function: str = None
        category: str = None
        file: str = None
        line: int = None

    @pytest.fixture(autouse=True)
    def init_args(self):
        parser = qutebrowser.get_argparser()
        args = parser.parse_args([])
        qtlog.init(args)

    def test_empty_message(self, caplog):
        """Make sure there's no crash with an empty message."""
        qtlog.qt_message_handler(qtcore.QtMsgType.QtDebugMsg, self.Context(), "")
        assert caplog.messages == ["Logged empty message!"]
