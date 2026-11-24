# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=wildcard-import,unused-wildcard-import

"""Wrapped Qt imports for PyQt6.sip.

All code in qutebrowser should use this module instead of importing from
PyQt/sip directly.

Any API exported from this module is based on the PyQt6.sip API:
https://www.riverbankcomputing.com/static/Docs/PyQt6/api/sip/sip-module.html
"""

try:
    from PyQt6.sip import *
except ImportError:
    # Some distributions package PyQt with a top-level "sip" rather than
    # "PyQt6.sip".
    from sip import *  # type: ignore[import-not-found]
