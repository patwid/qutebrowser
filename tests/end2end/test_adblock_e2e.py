# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""End to end tests for adblocking."""

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
