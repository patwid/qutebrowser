# SPDX-FileCopyrightText: Imran Sobir
# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import time

from qutebrowser.qt.core import QUrl
import pytest

from qutebrowser.browser import qutescheme
from qutebrowser.utils import resources, urlmatch
from qutebrowser.misc import guiprocess


class TestDataForUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            # QUrl.UrlFormattingOption.StripTrailingSlash
            (QUrl("qute://abc/xyz/"), QUrl("qute://abc/xyz")),
            # QUrl.UrlFormattingOption.NormalizePathSegments
            (QUrl("qute://abc/uvw/../xyz"), QUrl("qute://abc/xyz")),
            # Adding host trailing slash
            (QUrl("qute://abc"), QUrl("qute://abc/")),
            (QUrl("qute://abc?q=42"), QUrl("qute://abc/?q=42")),
            # path -> host
            (QUrl("qute:abc"), QUrl("qute://abc/")),
            (QUrl("qute:abc?q=42"), QUrl("qute://abc/?q=42")),
        ],
        ids=lambda url: url.toString(),
    )
    def test_redirects(self, url: QUrl, expected: QUrl) -> None:
        with pytest.raises(qutescheme.Redirect) as exc:
            qutescheme.data_for_url(url)
        assert exc.value.url == expected

    def test_invalid_redirect(self) -> None:
        url = QUrl("qute:-")
        with pytest.raises(
            qutescheme.UrlInvalidError, match=r"Invalid host \(from path\): '-'"
        ):
            qutescheme.data_for_url(url)


class TestJavascriptHandler:

    """Test the qute://javascript endpoint."""

    # Tuples of fake JS files and their content.
    js_files = [
        ('foo.js', "var a = 'foo';"),
        ('bar.js', "var a = 'bar';"),
    ]

    @pytest.fixture(autouse=True)
    def patch_read_file(self, monkeypatch):
        """Patch resources.read_file to return few fake JS files."""
        def _read_file(path):
            """Faked resources.read_file."""
            for filename, content in self.js_files:
                if path == os.path.join('javascript', filename):
                    return content
            raise OSError("File not found {}!".format(path))

        monkeypatch.setattr(resources, 'read_file', _read_file)

    @pytest.mark.parametrize("filename, content", js_files)
    def test_qutejavascript(self, filename, content):
        url = QUrl("qute://javascript/{}".format(filename))
        _mimetype, data = qutescheme.qute_javascript(url)

        assert data == content

    def test_qutejavascript_404(self):
        url = QUrl("qute://javascript/404.js")

        with pytest.raises(qutescheme.SchemeOSError):
            qutescheme.data_for_url(url)

    def test_qutejavascript_empty_query(self):
        url = QUrl("qute://javascript")

        with pytest.raises(qutescheme.UrlInvalidError):
            qutescheme.qute_javascript(url)


class TestProcessHandler:

    """Test the qute://process endpoint."""

    def test_invalid_pid(self):
        with pytest.raises(qutescheme.UrlInvalidError, match='Invalid PID blah'):
            qutescheme.qute_process(QUrl('qute://process/blah'))

    def test_missing_process(self, monkeypatch):
        monkeypatch.setattr(guiprocess, 'all_processes', {})
        with pytest.raises(qutescheme.NotFoundError, match='No process 1234'):
            qutescheme.qute_process(QUrl('qute://process/1234'))

    def test_existing_process(self, qtbot, py_proc):
        proc = guiprocess.GUIProcess('testprocess')

        with qtbot.wait_signal(proc.finished, timeout=5000):
            proc.start(*py_proc("print('AT&T')"))

        _mimetype, data = qutescheme.qute_process(QUrl(f'qute://process/{proc.pid}'))
        print(data)

        assert f'<title>Process {proc.pid}</title>' in data
        assert '-c &#39;print(' in data
        assert 'Testprocess exited successfully.' in data
        assert f'<pre>AT&amp;T{os.linesep}</pre>' in data
        assert 'No output.' in data  # stderr


class TestHistoryHandler:

    """Test the qute://history endpoint."""

    @pytest.fixture(scope="module")
    def now(self):
        return int(time.time())

    @pytest.fixture
    def entries(self, now):
        """Create fake history entries."""
        # create 12 history items spaced 6 hours apart, starting from now
        entry_count = 12
        interval = 6 * 60 * 60

        items = []
        for i in range(entry_count):
            entry_atime = now - i * interval
            entry = {"atime": str(entry_atime),
                     "url": QUrl("http://www.x.com/" + str(i)),
                     "title": "Page " + str(i)}
            items.insert(0, entry)

        return items

    @pytest.fixture(autouse=True)
    def fake_history(self, web_history, fake_args, entries):
        """Create fake history."""
        for item in entries:
            web_history.add_url(**item)

    @pytest.mark.parametrize("start_time_offset, expected_item_count", [
        (0, 4),
        (24*60*60, 4),
        (48*60*60, 4),
        (72*60*60, 0)
    ])
    def test_qutehistory_data(self, start_time_offset, expected_item_count,
                              now):
        """Ensure qute://history/data returns correct items."""
        start_time = now - start_time_offset
        url = QUrl("qute://history/data?start_time=" + str(start_time))
        _mimetype, data = qutescheme.qute_history(url)
        items = json.loads(data)

        assert len(items) == expected_item_count

        # test times
        end_time = start_time - 24*60*60
        for item in items:
            assert item['time'] <= start_time
            assert item['time'] > end_time

    def test_exclude(self, web_history, now, config_stub):
        """Make sure the completion.web_history.exclude setting is not used."""
        config_stub.val.completion.web_history.exclude = ['www.x.com']

        url = QUrl("qute://history/data?start_time={}".format(now))
        _mimetype, data = qutescheme.qute_history(url)
        items = json.loads(data)
        assert items

    def test_qute_history_benchmark(self, web_history, benchmark, now):
        r = range(20000)
        entries = {
            'atime': [int(now - t) for t in r],
            'url': ['www.x.com/{}'.format(t) for t in r],
            'title': ['x at {}'.format(t) for t in r],
            'redirect': [False for _ in r],
        }

        web_history.insert_batch(entries)
        url = QUrl("qute://history/data?start_time={}".format(now))
        _mimetype, data = benchmark(qutescheme.qute_history, url)
        assert len(json.loads(data)) > 1


class TestHelpHandler:

    """Tests for qute://help."""

    @pytest.fixture
    def data_patcher(self, monkeypatch):
        def _patch(path, data):
            def _read_file(name):
                assert path == name
                return data.decode('utf-8')

            def _read_file_binary(name):
                assert path == name
                return data

            monkeypatch.setattr(qutescheme.resources, 'read_file', _read_file)
            monkeypatch.setattr(qutescheme.resources,
                                'read_file_binary', _read_file_binary)
        return _patch

    def test_unknown_file_type(self, data_patcher):
        data_patcher('html/doc/foo.bin', b'\xff')
        mimetype, data = qutescheme.qute_help(QUrl('qute://help/foo.bin'))
        assert mimetype == 'application/octet-stream'
        assert data == b'\xff'


class TestQuteConfigdiff:

    """Test the qute://configdiff handler."""

    @pytest.fixture(autouse=True)
    def prepare_config(self, config_stub):
        config_stub.set_obj(
            "content.javascript.enabled",
            True,
            pattern=urlmatch.UrlPattern("chrome-devtools://*"),
            hide_userconfig=True,
        )

    @pytest.mark.parametrize("url, expected", [
        (
            "qute://configdiff/",
            b"<Default configuration>",
        ),
        (
            "qute://configdiff/?include_hidden=true",
            b'chrome-devtools://*: content.javascript.enabled = true',
        )
    ])
    def test_default_config(self, config_stub, url, expected):
        _mimetype, data = qutescheme.data_for_url(QUrl(url))
        assert data == expected

    def test_changes(self, config_stub):
        config_stub.set_obj("content.images", False)
        url = QUrl('qute://configdiff/')
        _mimetype, data = qutescheme.data_for_url(url)
        assert data == b'content.images = false'
