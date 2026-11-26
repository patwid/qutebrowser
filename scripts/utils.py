# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later


"""Utility functions for scripts."""

import os
import os.path
import sys


use_color = True


fg_colors = {
    'reset': 0,
    'bold': 1,
    'black': 30,
    'red': 31,
    'green': 32,
    'yellow': 33,
    'blue': 34,
    'magenta': 35,
    'cyan': 36,
    'white': 37,
}


bg_colors = {name: col + 10 for name, col in fg_colors.items()}


def _esc(code):
    """Get an ANSI color code based on a color number."""
    return '\033[{}m'.format(code)


def print_col(text, color, file=sys.stdout):
    """Print a colorized text."""
    if use_color:
        fg = _esc(fg_colors[color.lower()])
        reset = _esc(fg_colors['reset'])
        print(''.join([fg, text, reset]), file=file, flush=True)
    else:
        print(text, file=file, flush=True)


def print_error(text):
    print_col(text, 'red', file=sys.stderr)


def print_title(text):
    """Print a title."""
    print()
    print_col("==================== {} ====================".format(text),
              'yellow')


def change_cwd():
    """Change the scripts cwd if it was started inside the script folder."""
    cwd = os.getcwd()
    if os.path.split(cwd)[1] == 'scripts':
        os.chdir(os.path.join(cwd, os.pardir))
