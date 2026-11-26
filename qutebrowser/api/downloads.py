# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""APIs related to downloading files."""


from qutebrowser.qt.core import QUrl

from qutebrowser.misc import httpclient


#: A download of some data into a file object.
TempDownload = httpclient.Fetch


def download_temp(url: QUrl) -> TempDownload:
    """Download the given URL into a file object.

    The download is not saved to disk and not shown in the download bar.

    Returns a ``TempDownload`` object, which triggers a ``finished`` signal
    when the download has finished::

        dl = downloads.download_temp(QUrl("https://www.example.com/"))
        dl.finished.connect(functools.partial(on_download_finished, dl))

    The ``finished`` signal is emitted for failed downloads as well. After the
    download has finished, its ``successful`` attribute can be checked to make
    sure it finished successfully. If so, its contents can be
    read by accessing the ``fileobj`` attribute::

        def on_download_finished(download: downloads.TempDownload) -> None:
            if download.successful:
                print(download.fileobj.read())
                download.fileobj.close()
    """
    return httpclient.fetch(url)
