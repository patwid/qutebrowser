# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.browser.webengine.cosmetic."""

import json

import pytest

pytest.importorskip("qutebrowser.qt.webenginecore")

from qutebrowser.browser.webengine import cosmetic
from qutebrowser.components import braveadblock


class FakeBlocker:

    """A stand-in for braveadblock.BraveAdBlocker."""

    def __init__(self):
        self.generic_calls = []

    def cosmetic_resources(self, url):
        if url.host() != "example.com":
            return None
        return braveadblock.CosmeticResources(
            hide_selectors=[".ad"],
            style_selectors={".foo": ["color: red"]},
            exceptions={".kept"},
            generic=True,
        )

    def generic_hide_selectors(self, *, classes, ids, exceptions):
        self.generic_calls.append((classes, ids, exceptions))
        return ["." + name for name in classes] + ["#" + name for name in ids]


@pytest.fixture
def blocker(monkeypatch):
    blocker = FakeBlocker()
    monkeypatch.setattr(braveadblock, "ad_blocker", blocker)
    return blocker


@pytest.fixture
def bridge(qapp):
    return cosmetic.CosmeticBridge()


def test_js_code(qapp):
    code = cosmetic.js_code()
    assert "QWebChannel" in code
    assert "window._qutebrowser.cosmetic" in code


def test_rules(bridge, blocker):
    rules = json.loads(bridge.rules("tok", "https://example.com/page"))
    assert rules == {
        "token": "tok",
        "enabled": True,
        "hide": [".ad"],
        "style": {".foo": ["color: red"]},
        "generic": True,
    }


def test_rules_disabled(bridge, blocker):
    assert json.loads(bridge.rules("tok", "https://example.org/")) == {
        "token": "tok", "enabled": False}


def test_rules_no_blocker(bridge, monkeypatch):
    monkeypatch.setattr(braveadblock, "ad_blocker", None)
    assert json.loads(bridge.rules("tok", "https://example.com/")) == {
        "token": "tok", "enabled": False}
    request = '{"token": "tok", "classes": ["a"], "ids": []}'
    assert json.loads(bridge.generic_selectors(request)) == {
        "token": "tok", "selectors": []}


def test_generic_selectors(bridge, blocker):
    bridge.rules("tok", "https://example.com/page")
    request = json.dumps(
        {"token": "tok", "classes": ["one", "two"], "ids": ["three"]})
    assert json.loads(bridge.generic_selectors(request)) == {
        "token": "tok", "selectors": [".one", ".two", "#three"]}
    assert blocker.generic_calls == [(["one", "two"], ["three"], {".kept"})]


def test_exceptions_reset(bridge, blocker):
    """Exceptions of a page must not apply to the next one."""
    bridge.rules("tok", "https://example.com/page")
    bridge.rules("tok", "https://example.org/page")
    bridge.generic_selectors('{"classes": ["one"], "ids": []}')
    assert blocker.generic_calls == [(["one"], [], set())]


@pytest.mark.parametrize("request_data, expected", [
    ("not json", ([], [])),
    ("[]", ([], [])),
    ('{"classes": "abc", "ids": 42}', ([], [])),
    ('{"classes": ["ok", 1, null, "", {"a": 1}]}', (["ok"], [])),
    (json.dumps({"ids": ["x" * 256, "x" * 257]}), ([], ["x" * 256])),
])
def test_generic_selectors_invalid(bridge, blocker, request_data, expected):
    """What a page sends us is validated."""
    answer = json.loads(bridge.generic_selectors(request_data))
    classes, ids = expected
    assert blocker.generic_calls == [(classes, ids, set())]
    assert answer["token"] is None


def test_generic_selectors_limit(bridge, blocker):
    names = [f"c{i}" for i in range(cosmetic._MAX_NAMES + 10)]
    bridge.generic_selectors(json.dumps({"classes": names, "ids": []}))
    assert len(blocker.generic_calls[0][0]) == cosmetic._MAX_NAMES
