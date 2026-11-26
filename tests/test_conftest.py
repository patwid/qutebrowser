# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Various meta-tests for conftest.py."""


import warnings

import pytest


def test_qapp_name(qapp):
    """Make sure the QApplication name is changed when we use qapp."""
    assert qapp.applicationName() == 'qute_test'


def test_no_qapp(request):
    """Make sure a test without qapp doesn't use qapp (via autouse)."""
    assert 'qapp' not in request.fixturenames


def test_fail_on_warnings():
    with pytest.raises(PendingDeprecationWarning):
        warnings.warn('test', PendingDeprecationWarning)
