#!/usr/bin/env python3

# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Very simple browser for testing purposes."""

import sys
import argparse

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView


def parse_args():
    """Parse commandline arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('url', help='The URL to open',
                        nargs='?', default='https://qutebrowser.org/')
    return parser.parse_known_args()[0]


if __name__ == '__main__':
    args = parse_args()
    app = QApplication(sys.argv)
    wv = QWebEngineView()

    wv.loadStarted.connect(lambda: print("Loading started"))
    wv.loadProgress.connect(lambda p: print("Loading progress: {}%".format(p)))
    wv.loadFinished.connect(lambda: print("Loading finished"))

    wv.load(QUrl.fromUserInput(args.url))
    wv.show()

    app.exec()
