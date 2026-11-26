# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.misc.httpclient."""

import logging

from qutebrowser.qt.core import QUrl

import pytest

from qutebrowser.config import websettings
from qutebrowser.misc import httpclient
from qutebrowser.utils import usertypes


@pytest.fixture(autouse=True)
def user_agent(monkeypatch):
    monkeypatch.setattr(websettings, 'user_agent', lambda url: 'test-agent')


def test_fetch_success(qtbot, tmp_path):
    path = tmp_path / 'list.txt'
    path.write_bytes(b'some data')

    download = httpclient.fetch(QUrl.fromLocalFile(str(path)))
    assert not download.successful
    with qtbot.wait_signal(download.finished):
        pass

    assert download.successful
    assert download.error_msg is None
    assert download.fileobj.getvalue() == b'some data'
    assert download not in httpclient._running_fetches


def test_fetch_error(qtbot, tmp_path, message_mock, caplog):
    url = QUrl.fromLocalFile(str(tmp_path / 'does-not-exist'))

    with caplog.at_level(logging.ERROR):
        download = httpclient.fetch(url)
        with qtbot.wait_signal(download.finished):
            pass

    assert not download.successful
    assert download.error_msg
    assert download.fileobj.getvalue() == b''
    assert download not in httpclient._running_fetches

    msg = message_mock.getmsg(usertypes.MessageLevel.error)
    assert msg.text == f"Download error: {download.error_msg}"
