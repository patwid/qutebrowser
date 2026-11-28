# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test webenginetab."""


import pytest
QtWebEngineCore = pytest.importorskip("qutebrowser.qt.webenginecore")
QWebEnginePage = QtWebEngineCore.QWebEnginePage
QWebEngineScriptCollection = QtWebEngineCore.QWebEngineScriptCollection
QWebEngineScript = QtWebEngineCore.QWebEngineScript

webenginetab = pytest.importorskip(
    "qutebrowser.browser.webengine.webenginetab")


class TestFindFlags:

    @pytest.mark.parametrize("case_sensitive, backward, expected", [
        (True, True, (QWebEnginePage.FindFlag.FindCaseSensitively |
                      QWebEnginePage.FindFlag.FindBackward)),
        (True, False, QWebEnginePage.FindFlag.FindCaseSensitively),
        (False, True, QWebEnginePage.FindFlag.FindBackward),
        (False, False, QWebEnginePage.FindFlag(0)),
    ])
    def test_to_qt(self, case_sensitive, backward, expected):
        flags = webenginetab._FindFlags(
            case_sensitive=case_sensitive,
            backward=backward,
        )
        assert flags.to_qt() == expected

    @pytest.mark.parametrize("case_sensitive, backward, expected", [
        (True, True, True),
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ])
    def test_bool(self, case_sensitive, backward, expected):
        flags = webenginetab._FindFlags(
            case_sensitive=case_sensitive,
            backward=backward,
        )
        assert bool(flags) == expected

    @pytest.mark.parametrize("case_sensitive, backward, expected", [
        (True, True, "FindCaseSensitively|FindBackward"),
        (True, False, "FindCaseSensitively"),
        (False, True, "FindBackward"),
        (False, False, "<no find flags>"),
    ])
    def test_str(self, case_sensitive, backward, expected):
        flags = webenginetab._FindFlags(
            case_sensitive=case_sensitive,
            backward=backward,
        )
        assert str(flags) == expected


class TestWebEnginePermissions:

    def test_clipboard_value(self):
        # Ensure the ClipboardReadWrite permission is in the permission map,
        # despite us specifying it by number.
        permissions_cls = webenginetab._WebEnginePermissions
        try:
            clipboard = QWebEnginePage.Feature.ClipboardReadWrite
        except AttributeError:
            pytest.skip("enum member not available")
        assert clipboard in permissions_cls._options
        assert clipboard in permissions_cls._messages
