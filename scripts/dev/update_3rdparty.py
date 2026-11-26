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


def test_dicts():
    """Test available dictionaries."""
    from scripts import dictcli
    from qutebrowser.config import configdata
    configdata.init()
    for lang in dictcli.available_languages():
        print('Testing dictionary {}... '.format(lang.code), end='')
        lang_url = urllib.parse.urljoin(dictcli.API_URL, lang.remote_filename)
        request = urllib.request.Request(lang_url, method='HEAD')
        with urllib.request.urlopen(request) as response:
            if response.status == 200:
                print('OK')
            else:
                print('ERROR: {}'.format(response.status))


def run(*, ace=False, dicts=False):
    """Update components based on the given arguments."""
    if ace:
        update_ace()
    if dicts:
        test_dicts()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--dicts', '-d',
        help='Test whether all available dictionaries '
        'can be reached at the remote repository.',
        required=False, action='store_true')
    args = parser.parse_args()
    run(ace=True, dicts=args.dicts)


if __name__ == '__main__':
    main()
