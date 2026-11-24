# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check how Qt behaves when trying to execute JS."""


import pytest


@pytest.mark.usefixtures('redirect_webengine_data')
@pytest.mark.parametrize('js_enabled, world, expected', [
    # main world
    (True, 0, 2.0),
    (False, 0, None),
    # application world
    (True, 1, 2.0),
    (False, 1, 2.0),
    # user world
    (True, 2, 2.0),
    (False, 2, 2.0),
])
def test_simple_js_webengine(qtbot, webengineview, qapp,
                             js_enabled, world, expected):
    """With QtWebEngine, runJavaScript works even when JS is off."""
    # If we get there (because of the webengineview fixture) we can be certain
    # QtWebEngine is available
    from qutebrowser.qt.webenginecore import QWebEngineSettings, QWebEngineScript

    assert world in [QWebEngineScript.ScriptWorldId.MainWorld,
                     QWebEngineScript.ScriptWorldId.ApplicationWorld,
                     QWebEngineScript.ScriptWorldId.UserWorld]

    settings = webengineview.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, js_enabled)
    qapp.processEvents()

    page = webengineview.page()

    with qtbot.wait_callback() as callback:
        page.runJavaScript('1 + 1', world, callback)

    callback.assert_called_with(expected)
