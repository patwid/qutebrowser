# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Commands relating to ad blocking."""

from qutebrowser.api import cmdutils
from qutebrowser.components import braveadblock


@cmdutils.register()
def adblock_update() -> None:
    """Update the block lists of the Brave ad blocker."""
    if braveadblock.ad_blocker is None:
        raise cmdutils.CommandError("The 'adblock' dependency is not installed.")
    braveadblock.ad_blocker.adblock_update()
