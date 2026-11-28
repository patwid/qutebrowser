# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest_bdd as bdd
bdd.scenarios('javascript.feature')


@bdd.then("the window sizes should be the same")
def check_window_sizes(quteproc):
    hidden = quteproc.wait_for_js('hidden window size: *')
    quteproc.send_cmd(':jseval --world main updateText("visible")')
    visible = quteproc.wait_for_js('visible window size: *')
    hidden_size = hidden.message.split()[-1]
    visible_size = visible.message.split()[-1]
    assert hidden_size == visible_size
