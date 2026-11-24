# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=import-error,wildcard-import,unused-wildcard-import

"""Wrapped Qt imports for Qt Core.

All code in qutebrowser should use this module instead of importing from
PyQt directly.

Any API exported from this module is based on the Qt 6 API:
https://doc.qt.io/qt-6/qtcore-index.html
"""

from typing import TYPE_CHECKING
from PyQt6.QtCore import *

if TYPE_CHECKING:
    from qutebrowser.qt._core_pyqtproperty import pyqtProperty
