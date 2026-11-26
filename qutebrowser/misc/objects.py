# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Various global objects."""

# NOTE: We need to be careful with imports here, as this is imported from
# earlyinit.

import argparse
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from qutebrowser import app
    from qutebrowser.commands import command


commands: dict[str, 'command.Command'] = {}
debug_flags: set[str] = set()
args = cast(argparse.Namespace, None)
qapp = cast('app.Application', None)
