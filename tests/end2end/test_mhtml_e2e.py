# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test mhtml downloads based on sample files."""

import pathlib

import pytest


def collect_tests():
    basedir = pathlib.Path(__file__).parent
    datadir = basedir / 'data' / 'downloads' / 'mhtml'
    files = [x.name for x in datadir.iterdir()]
    return files


class DownloadDir:

    """Abstraction over a download directory."""

    def __init__(self, tmp_path, config):
        self._tmp_path = tmp_path
        self._config = config
        self.location = str(tmp_path)

    def read_file(self):
        files = list(self._tmp_path.iterdir())
        assert len(files) == 1
        return files[0].read_text(encoding='utf-8').splitlines()

    def sanity_check_mhtml(self):
        assert 'Content-Type: multipart/related' in '\n'.join(self.read_file())


@pytest.fixture
def download_dir(tmp_path, pytestconfig):
    return DownloadDir(tmp_path, pytestconfig)


@pytest.mark.parametrize('test_name', collect_tests())
def test_mhtml(test_name, download_dir, quteproc, server):
    quteproc.set_setting('downloads.location.directory', download_dir.location)
    quteproc.set_setting('downloads.location.prompt', 'false')

    test_dir = (pathlib.Path(__file__).parent.resolve()
                / 'data' / 'downloads' / 'mhtml' / test_name)
    test_path = 'data/downloads/mhtml/{}'.format(test_name)

    url_path = '{}/{}.html'.format(test_path, test_name)
    quteproc.open_path(url_path)

    download_dest = (pathlib.Path(download_dir.location)
                     / '{}-downloaded.mht'.format(test_name))

    # Wait for favicon.ico to be loaded if there is one
    if (test_dir / 'favicon.png').exists():
        server.wait_for(path='/{}/favicon.png'.format(test_path))

    # Discard all requests that were necessary to display the page
    server.clear_data()
    quteproc.send_cmd(':download --mhtml --dest "{}"'.format(download_dest))
    quteproc.wait_for(category='downloads',
                      message='File successfully written.')

    download_dir.sanity_check_mhtml()
