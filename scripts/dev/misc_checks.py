#!/usr/bin/env python3

# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Various small code checkers."""

import os
import os.path
import re
import sys
import argparse
import subprocess
import tokenize
import traceback
import pathlib
from collections.abc import Iterator

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts import utils

BINARY_EXTS = {'.png', '.icns', '.ico', '.bmp', '.gz', '.bin', '.pdf',
               '.sqlite', '.woff2', '.whl', '.egg'}


def _get_files(
        *,
        verbose: bool,
        ignored: list[pathlib.Path] | None = None
) -> Iterator[pathlib.Path]:
    """Iterate over all files and yield filenames."""
    filenames = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )
    all_ignored = ignored or []

    for filename in filenames.stdout.split('\0'):
        path = pathlib.Path(filename)
        is_ignored = any(path == p or p in path.parents for p in all_ignored)
        if not filename or path.suffix in BINARY_EXTS or is_ignored:
            continue

        try:
            with tokenize.open(path):
                pass
        except SyntaxError as e:
            # Could not find encoding
            utils.print_col("{} - maybe {} should be added to BINARY_EXTS?".format(
                str(e).capitalize(), path.suffix), 'yellow')
            continue

        if verbose:
            print(path)

        yield path


def check_git(_args: argparse.Namespace | None = None) -> bool:
    """Check for uncommitted git files."""
    if not os.path.isdir(".git"):
        print("No .git dir, ignoring")
        print()
        return False
    untracked = []
    gitst = subprocess.run(['git', 'status', '--porcelain'], check=True,
                           stdout=subprocess.PIPE).stdout
    gitst = gitst.decode('UTF-8').strip()
    for line in gitst.splitlines():
        s, name = line.split(maxsplit=1)
        if s == '??' and name != '.venv/':
            untracked.append(name)
    status = True
    if untracked:
        status = False
        utils.print_col("Untracked files:", 'red')
        print('\n'.join(untracked))
    print()
    return status


def _check_spelling_file(path, fobj, patterns):
    ok = True
    for num, line in enumerate(fobj, start=1):
        for pattern, explanation in patterns:
            match = pattern.search(line)
            if match:
                ok = False
                print(f'{path}:{num}: ', end='')
                utils.print_col(f'Found "{match.group(0)}" - {explanation}', 'blue')
    return ok


def _check_spelling_all(
    args: argparse.Namespace,
    ignored: list[pathlib.Path],
    patterns: list[tuple[re.Pattern, str]],
) -> bool | None:
    try:
        ok = True
        for path in _get_files(verbose=args.verbose, ignored=ignored):
            with tokenize.open(str(path)) as f:
                if not _check_spelling_file(path, f, patterns):
                    ok = False
        print()
        return ok
    except Exception:
        traceback.print_exc()
        return None


def check_spelling(args: argparse.Namespace) -> bool | None:
    """Check commonly misspelled words."""
    # Words which I often misspell
    words = {'behaviour', 'quitted', 'likelyhood', 'sucessfully',
             'occur[^rs .!,]', 'seperator', 'explicitely', 'auxillary',
             'accidentaly', 'ambigious', 'loosly', 'initialis', 'convienence',
             'similiar', 'uncommited', 'reproducable', 'an user',
             'convienience', 'wether', 'programatically', 'splitted',
             'exitted', 'mininum', 'resett?ed', 'recieved', 'regularily',
             'underlaying', 'inexistant', 'elipsis', 'commiting', 'existant',
             'resetted', 'similarily', 'informations', 'an url', 'treshold',
             'artefact', 'an unix', 'an utf', 'an unicode', 'unparseable',
             'dependancies', 'convertable', 'chosing', 'authentification'}

    # Words which look better when split, but might need some fine tuning.
    words |= {'webelements', 'mouseevent', 'keysequence', 'normalmode',
              'eventloops', 'sizehint', 'statemachine', 'metaobject',
              'logrecord'}

    patterns = [
        (
            re.compile(r'[{}{}]{}'.format(w[0], w[0].upper(), w[1:])),
            "Common misspelling or non-US spelling"
        ) for w in words
    ]

    qtbot_methods = {
        'keyPress',
        'keyRelease',
        'keyClick',
        'keyClicks',
        'keyEvent',
        'mousePress',
        'mouseRelease',
        'mouseClick',
        'mouseMove',
        'mouseDClick',
        'keySequence',
    }

    qtbot_excludes = '|'.join(qtbot_methods)

    patterns += [
        (
            re.compile(r'(?i)# noqa(?!: )'),
            "Don't use a blanket 'noqa', use something like 'noqa: X123' instead.",
        ),
        (
            re.compile(r'# type: (?!ignore(\[|$))'),
            "Don't use type comments, use type annotations instead.",
        ),
        (
            re.compile(r': typing\.'),
            "Don't use typing.SomeType, do 'from typing import SomeType' instead.",
        ),
        (
            re.compile(r"""monkeypatch\.setattr\(['"]"""),
            "Don't use monkeypatch.setattr('obj.attr', value), use "
            "setattr(obj, 'attr', value) instead.",
        ),
        (
            re.compile(r'(exec|print)_\('),
            ".exec_()/.print_() are removed in PyQt 6, use .exec()/.print() instead.",
        ),
        (
            re.compile(r'qApp'),
            "qApp is removed in PyQt 6, use QApplication.instance() instead.",
        ),
        (
            re.compile(r'PYQT_CONFIGURATION'),
            "PYQT_CONFIGURATION is removed in PyQt 6",
        ),
        (
            re.compile(r'Q_(ENUM|FLAG)'),
            "Q_ENUM and Q_FLAG are removed in PyQt 6",
        ),
        (
            re.compile(r'attr\.(s|ib)($|\()'),
            "attrs have been replaced by dataclasses in qutebrowser.",
        ),
        (
            re.compile(r'http://www\.gnu\.org/licenses/'),
            "use https:// URL.",
        ),
        (
            re.compile(r'IOError'),
            "use OSError",
        ),
        (
            re.compile(fr'qtbot\.(?!{qtbot_excludes})[a-z]+[A-Z].*'),
            "use snake-case instead",
        ),
        (
            re.compile(r'\.joinpath\((?!\*)'),
            "use the / operator for joining paths",
        ),
        (
            re.compile(r"""pathlib\.Path\(["']~["']\)\.expanduser\(\)"""),
            "use pathlib.Path.home() instead",
        ),
        (
            re.compile(r'pathlib\.Path\(tmp_path\)'),
            "tmp_path already is a pathlib.Path",
        ),
        (
            re.compile(r'pathlib\.Path\(tmpdir\)'),
            "use tmp_path instead",
        ),
        (
            re.compile(r' Copyright 2'),
            "use 'SPDX-FileCopyrightText: ...' without year instead",
        ),
        (
            re.compile(r'qutebrowser is free software: you can redistribute'),
            "use 'SPDX-License-Identifier: GPL-3.0-or-later' instead",
        ),
        (
            re.compile(r'QTimer\(.*\)$'),
            "use usertypes.Timer() instead of a plain QTimer",
        ),
    ]

    # Files which should be ignored, e.g. because they come from another
    # package
    hint_data = pathlib.Path('tests', 'end2end', 'data', 'hints')
    ignored = [
        pathlib.Path('scripts', 'dev', 'misc_checks.py'),
        pathlib.Path('qutebrowser', 'qt', '_core_pyqtproperty.py'),
        hint_data / 'ace' / 'ace.js',
        hint_data / 'bootstrap' / 'bootstrap.css',
    ]
    return _check_spelling_all(args=args, ignored=ignored, patterns=patterns)


def check_pyqt_imports(args: argparse.Namespace) -> bool | None:
    """Check for direct PyQt imports."""
    ignored = [
        pathlib.Path("qutebrowser", "qt"),
        pathlib.Path("scripts"),
    ]
    patterns = [
        (
            re.compile(r"from PyQt.* import"),
            "Use 'from qutebrowser.qt.MODULE import ...' instead",
        ),
        (
            re.compile(r"import PyQt.*"),
            "Use 'import qutebrowser.qt.MODULE' instead",
        )
    ]
    return _check_spelling_all(args=args, ignored=ignored, patterns=patterns)


def check_vcs_conflict(args: argparse.Namespace) -> bool | None:
    """Check VCS conflict markers."""
    try:
        ok = True
        for path in _get_files(verbose=args.verbose):
            if path.suffix in {'.rst', '.asciidoc'}:
                # False positives
                continue
            with tokenize.open(path) as f:
                for line in f:
                    if any(line.startswith(c * 7) for c in '<>=|'):
                        print("Found conflict marker in {}".format(path))
                        ok = False
        print()
        return ok
    except Exception:
        traceback.print_exc()
        return None


def check_vim_modelines(args: argparse.Namespace) -> bool:
    """Check that we're not using vim modelines."""
    ok = True
    try:
        for path in _get_files(verbose=args.verbose):
            with tokenize.open(str(path)) as f:
                for num, line in enumerate(f, start=1):
                    if not line.startswith("# vim:"):
                        continue
                    print(f"{path}:{num}: Remove vim modeline "
                          "(deprecated in favor of .editorconfig)")
                    ok = False
    except Exception:
        traceback.print_exc()
        ok = False

    return ok


def main() -> int:
    checkers = {
        'git': check_git,
        'vcs': check_vcs_conflict,
        'spelling': check_spelling,
        'pyqt-imports': check_pyqt_imports,
        'vim-modelines': check_vim_modelines,
    }

    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true', help='Show checked filenames')
    parser.add_argument('checker',
                        choices=list(checkers) + ['all'],
                        help="Which checker to run.")
    args = parser.parse_args()

    if args.checker == 'all':
        retvals = []
        for name, checker in checkers.items():
            utils.print_title(name)
            retvals.append(checker(args))
        return 0 if all(retvals) else 1

    checker = checkers[args.checker]
    ok = checker(args)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
