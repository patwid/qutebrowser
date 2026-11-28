# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""End to end tests for showing PDF files."""

import pytest


@pytest.fixture(autouse=True)
def download_dir(quteproc, tmp_path):
    path = tmp_path / 'downloads'
    path.mkdir()
    quteproc.set_setting('downloads.location.directory', str(path))
    quteproc.set_setting('downloads.location.prompt', 'false')
    return path


def test_pdf_viewer(quteproc, download_dir):
    quteproc.set_setting('content.pdf_viewer', 'true')
    quteproc.open_path('data/misc/test.pdf')
    assert not list(download_dir.iterdir())


def test_pdf_downloaded(quteproc, download_dir):
    quteproc.set_setting('content.pdf_viewer', 'false')
    quteproc.open_path('data/misc/test.pdf', wait=False)
    quteproc.wait_for(category='downloads', message='Download test.pdf finished')
    assert [path.name for path in download_dir.iterdir()] == ['test.pdf']
