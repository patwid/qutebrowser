# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""Tests for qutebrowser.config.configexc."""

import textwrap

import pytest

from qutebrowser.config import configexc


def test_validation_error():
    e = configexc.ValidationError('val', 'msg')
    assert e.option is None
    assert str(e) == "Invalid value 'val' - msg"


@pytest.mark.parametrize('deleted, renamed, all_names, expected', [
    (False, None, [], "No option 'opt'"),
    (True, None, [], "No option 'opt' (this option was removed from qutebrowser)"),
    (False, 'new', [], "No option 'opt' (this option was renamed to 'new')"),
    (False, None, ["opto"], "No option 'opt' (did you mean 'opto'?)"),
    (False, None, ["thisdoesnotmatch"], "No option 'opt'"),
    (
        True,
        None,
        ["opto"],
        "No option 'opt' (this option was removed from qutebrowser)",
    ),
    (False, 'new', ["opto"], "No option 'opt' (this option was renamed to 'new')"),
])
def test_no_option_error(deleted, renamed, all_names, expected):
    e = configexc.NoOptionError(
        'opt',
        deleted=deleted,
        renamed=renamed,
        all_names=all_names,
    )
    assert e.option == 'opt'
    assert str(e) == expected


def test_no_option_error_clash():
    with pytest.raises(AssertionError):
        _ = configexc.NoOptionError('opt', deleted=True, renamed='foo')


def test_no_autoconfig_error():
    e = configexc.NoAutoconfigError('opt')
    expected = "The opt setting can only be set in config.py!"
    assert str(e) == expected


def test_no_pattern_error():
    e = configexc.NoPatternError('foo')
    expected = "The foo setting does not support URL patterns!"
    assert str(e) == expected


def test_desc_with_text():
    """Test ConfigErrorDesc.with_text."""
    old = configexc.ConfigErrorDesc("Error text", Exception("Exception text"))
    new = old.with_text("additional text")
    assert str(new) == 'Error text (additional text): Exception text'


@pytest.fixture
def errors():
    """Get a ConfigFileErrors object."""
    err1 = configexc.ConfigErrorDesc("Error text 1", Exception("Exception 1"))
    err2 = configexc.ConfigErrorDesc("Error text 2", Exception("Exception 2"),
                                     "Fake traceback")
    return configexc.ConfigFileErrors("config.py", [err1, err2])


def test_config_file_errors_str(errors):
    assert str(errors).splitlines() == [
        'Errors occurred while reading config.py:',
        '  Error text 1: Exception 1',
        '  Error text 2 - Exception: Exception 2',
    ]


def test_config_file_errors_html(errors):
    html = errors.to_html()
    assert textwrap.dedent(html) == textwrap.dedent("""
        Errors occurred while reading config.py:

        <ul>

            <li>
              <b>Error text 1</b>: Exception 1

            </li>

            <li>
              <b>Error text 2</b>: Exception 2

                <pre>
Fake traceback
                </pre>

            </li>

        </ul>
    """)
    # Make sure the traceback is not indented
    assert '<pre>\nFake traceback\n' in html


def test_config_file_errors_fatal():
    err = configexc.ConfigErrorDesc("Text", Exception("Text"))
    errors = configexc.ConfigFileErrors("state", [err], fatal=True)
    assert errors.fatal
