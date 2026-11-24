# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later


import pytest
import pytest_bdd as bdd


@pytest.fixture(autouse=True)
def init_fake_clipboard(quteproc):
    """Make sure the fake clipboard will be used."""
    quteproc.send_cmd(':debug-set-fake-clipboard')


@bdd.then(bdd.parsers.parse('"{text}" should be found'))
def check_found_text(request, quteproc, text):
    # WORKAROUND
    # This probably should work with Qt 5.9:
    # https://codereview.qt-project.org/#/c/192920/
    # https://codereview.qt-project.org/#/c/192921/
    # https://bugreports.qt.io/browse/QTBUG-53134
    # FIXME: Checking the selection via ":yank selection" doesn't actually work
    # with QtWebEngine, investigate why.
    pass


bdd.scenarios('search.feature')
