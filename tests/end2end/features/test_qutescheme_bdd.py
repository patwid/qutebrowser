# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest_bdd as bdd


bdd.scenarios('qutescheme.feature')


@bdd.then(bdd.parsers.parse("the {kind} request should be blocked"))
def request_blocked(request, quteproc, kind):
    blocking_js_msg = (
        "[http://localhost:*/data/misc/qutescheme_csrf.html:0] Not allowed to "
        "load local resource: qute://settings/set?*"
    )
    unsafe_redirect_msg = "Load error: ERR_UNSAFE_REDIRECT"

    # We mark qute:// as a local scheme, causing most requests being blocked
    # by Chromium internally (logging to the JS console).
    expected_messages = {
        'img': [blocking_js_msg],
        'link': [blocking_js_msg],
        'redirect': [unsafe_redirect_msg],
        'form': [blocking_js_msg],
    }

    for pattern in expected_messages[kind]:
        msg = quteproc.wait_for(message=pattern)
        msg.expected = True
