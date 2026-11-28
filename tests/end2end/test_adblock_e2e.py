# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""End to end tests for adblocking."""

import time

import pytest

try:
    import adblock
except ImportError:
    adblock = None

needs_adblock_lib = pytest.mark.skipif(
    adblock is None, reason="Needs 'adblock' library")


@needs_adblock_lib
def test_adblock(quteproc, server):
    quteproc.set_setting(
        'content.blocking.adblock.lists',
        f"['http://localhost:{server.port}/data/blocking/qutebrowser-adblock']"
    )
    quteproc.send_cmd(':adblock-update')
    quteproc.wait_for(
        message="braveadblock: Filters successfully read from 1 sources.")

    quteproc.open_path('data/blocking/external_logo.html')
    quteproc.wait_for(
        message="Request to https://qutebrowser.org/icons/qutebrowser.svg blocked "
                "by ad blocker.")


def _wait_for_content(quteproc, check):
    """Wait until the text of the page fulfills the given check."""
    content = None
    for _ in range(50):
        content = quteproc.get_content()
        if check(content):
            return content
        time.sleep(0.1)
    raise AssertionError(f"Unexpected page content: {content}")


@pytest.fixture
def cosmetic_rules(quteproc, server):
    quteproc.set_setting(
        'content.blocking.adblock.lists',
        f"['http://localhost:{server.port}/data/blocking/cosmetic-rules.txt']"
    )
    quteproc.send_cmd(':adblock-update')
    quteproc.wait_for(
        message="braveadblock: Filters successfully read from 1 sources.")


@needs_adblock_lib
def test_cosmetic_filtering(quteproc, cosmetic_rules):
    quteproc.open_path('data/blocking/cosmetic.html')
    content = _wait_for_content(quteproc, lambda text: 'hidden:' not in text)

    assert 'kept: regular content' in content
    assert 'kept: rule for another site' in content
    assert 'kept: generic rule with exception' in content

    # Elements added later are hidden too
    quteproc.send_cmd(':jseval --quiet --world main add_late_ad()')
    quteproc.wait_for_js('late ad added')
    _wait_for_content(quteproc, lambda text: 'hidden:' not in text)

    # Rules changing the style are applied
    quteproc.send_cmd(
        ':jseval --world main '
        'getComputedStyle(document.querySelector(".restyled")).visibility')
    quteproc.wait_for(message='hidden', category='message')


@needs_adblock_lib
@pytest.mark.parametrize('setting', [
    'content.blocking.adblock.hide_elements',
    'content.blocking.enabled',
])
def test_cosmetic_filtering_disabled(quteproc, cosmetic_rules, setting):
    quteproc.set_setting(setting, 'false')
    quteproc.open_path('data/blocking/cosmetic.html')
    quteproc.wait_for(message='Cosmetic rules disabled for *')
    content = quteproc.get_content()
    assert 'hidden: site-specific rule' in content
    assert 'hidden: generic class rule' in content
