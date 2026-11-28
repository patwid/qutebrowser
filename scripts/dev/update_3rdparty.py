#!/usr/bin/env python3

# SPDX-FileCopyrightText: Daniel Schadt
# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update all third-party-modules."""

import argparse
import urllib.request
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def update_ace():
    """Update ACE.

    See https://ace.c9.io/ and https://github.com/ajaxorg/ace-builds/
    """
    print("Updating ACE...")
    url = 'https://raw.githubusercontent.com/ajaxorg/ace-builds/master/src/ace.js'
    target_path = os.path.join('tests', 'end2end', 'data', 'hints', 'ace',
                               'ace.js')
    urllib.request.urlretrieve(url, target_path)
    urllib.request.urlcleanup()


def run(*, ace=False):
    """Update components based on the given arguments."""
    if ace:
        update_ace()


def main():
    argparse.ArgumentParser().parse_args()
    run(ace=True)


if __name__ == '__main__':
    main()
