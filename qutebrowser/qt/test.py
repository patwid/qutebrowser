# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=wildcard-import,unused-wildcard-import

"""Wrapped Qt imports for Qt Test.

All code in qutebrowser should use this module instead of importing from
PyQt directly.

Any API exported from this module is based on the Qt 6 API:
https://doc.qt.io/qt-6/qttest-index.html
"""

from PyQt6.QtTest import *
