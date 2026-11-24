# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.browser.network.httpheaders."""

import logging

import pytest
import hypothesis
from hypothesis import strategies
from qutebrowser.qt.core import QUrl

from qutebrowser.browser.network import httpheaders


@pytest.mark.parametrize('url, expected', [
    # Filename in the URL
    ('http://example.com/path', 'path'),
    ('http://example.com/foo/path', 'path'),
    # No filename at all
    ('http://example.com', 'qutebrowser-download'),
    ('http://example.com/', 'qutebrowser-download'),
])
def test_no_content_disposition(stubs, url, expected):
    reply = stubs.FakeNetworkReply(url=QUrl(url))
    inline, filename = httpheaders.parse_content_disposition(reply)
    assert inline
    assert filename == expected


@pytest.mark.parametrize('value', [
    # https://github.com/python/cpython/issues/87112
    'inline; 0*²'.encode("iso-8859-1"),
    # https://github.com/python/cpython/issues/81672
    b'"',
    # https://github.com/python/cpython/issues/93010
    b'attachment; 0*00="foo"',
])
def test_parse_content_disposition_invalid(value):
    with pytest.raises(httpheaders.ContentDispositionError):
        httpheaders.ContentDisposition.parse(value)


@pytest.mark.parametrize('template', [
    '{}',
    'attachment; filename="{}"',
    'inline; {}',
    'attachment; {}="foo"',
    "attachment; filename*=iso-8859-1''{}",
    'attachment; filename*={}',
])
@hypothesis.given(strategies.text(alphabet=[chr(x) for x in range(255)]))
def test_parse_content_disposition_hypothesis(caplog, template, stubs, s):
    """Test parsing headers based on templates which hypothesis completes."""
    header = template.format(s)
    reply = stubs.FakeNetworkReply(headers={'Content-Disposition': header})
    with caplog.at_level(logging.ERROR, 'network'):
        httpheaders.parse_content_disposition(reply)


@hypothesis.given(strategies.binary())
def test_content_disposition_directly_hypothesis(s):
    """Test rfc6266 parsing directly with binary data."""
    try:
        cd = httpheaders.ContentDisposition.parse(s)
        cd.filename()
    except httpheaders.ContentDispositionError:
        pass
