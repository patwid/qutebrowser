# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later


import sys
import os
import logging

import pytest

from qutebrowser import qutebrowser
from qutebrowser.config import qtargs, configdata
from qutebrowser.utils import version, utils


@pytest.fixture
def parser(mocker):
    """Fixture to provide an argparser.

    Monkey-patches .exit() of the argparser so it doesn't exit on errors.
    """
    parser = qutebrowser.get_argparser()
    mocker.patch.object(parser, 'exit', side_effect=Exception)
    return parser


@pytest.fixture
def version_patcher(monkeypatch):
    """Get a patching function to patch the QtWebEngine version."""
    def run(ver) -> bool:
        """Run patching.

        Return:
            True if we know the associated Chromium version, False otherwise
        """
        versions = version.WebEngineVersions.from_webengine(ver, source='test')
        monkeypatch.setattr(version, 'qtwebengine_versions', lambda: versions)
        return versions.chromium_major is not None

    return run


@pytest.fixture
def reduce_args(config_stub, version_patcher, monkeypatch):
    """Make sure no --disable-shared-workers/referer argument get added."""
    version_patcher('6.8.2')
    config_stub.val.content.headers.referer = 'always'
    config_stub.val.scrolling.bar = 'never'
    config_stub.val.qt.chromium.experimental_web_platform_features = 'never'
    config_stub.val.qt.workarounds.disable_accelerated_2d_canvas = 'never'
    config_stub.val.qt.workarounds.disable_accessibility = 'never'


@pytest.mark.usefixtures('reduce_args')
class TestQtArgs:

    @pytest.mark.parametrize('args, expected', [
        # No Qt arguments
        (['--debug'], [sys.argv[0]]),
        # Qt flag
        (['--debug', '--qt-flag', 'reverse'], [sys.argv[0], '--reverse']),
        # Qt argument with value
        (['--qt-arg', 'stylesheet', 'foo'],
         [sys.argv[0], '--stylesheet', 'foo']),
        # --qt-arg given twice
        (['--qt-arg', 'stylesheet', 'foo', '--qt-arg', 'geometry', 'bar'],
         [sys.argv[0], '--stylesheet', 'foo', '--geometry', 'bar']),
        # --qt-flag given twice
        (['--qt-flag', 'foo', '--qt-flag', 'bar'],
         [sys.argv[0], '--foo', '--bar']),
    ])
    def test_qt_args(self, request, monkeypatch, config_stub, args, expected, parser):
        """Test commandline with no Qt arguments given."""
        # passed unconditionally
        expected.insert(1, "--webEngineArgs")
        expected += [
            "--enable-features=WebRTCPipeWireCapturer",
            "--disable-features=DocumentPictureInPictureAPI",
            "--touch-events=disabled",
        ]
        parsed = parser.parse_args(args)
        assert qtargs.qt_args(parsed) == expected

    def test_qt_both(self, config_stub, parser):
        """Test commandline with a Qt argument and flag."""
        args = parser.parse_args(['--qt-arg', 'stylesheet', 'foobar',
                                  '--qt-flag', 'reverse'])
        qt_args = qtargs.qt_args(args)
        assert qt_args[0] == sys.argv[0]
        assert '--reverse' in qt_args
        assert '--stylesheet' in qt_args
        assert 'foobar' in qt_args

    def test_with_settings(self, config_stub, parser):
        parsed = parser.parse_args(['--qt-flag', 'foo'])
        config_stub.val.qt.args = ['bar']
        args = qtargs.qt_args(parsed)
        assert args[0] == sys.argv[0]
        for arg in ['--foo', '--bar']:
            assert arg in args


def test_no_webengine_available(monkeypatch, config_stub, parser, stubs):
    """Test that we don't fail if QtWebEngine is requested but unavailable.

    Note this is not inside TestQtArgs because we don't want the reduce_args patching
    here.
    """
    fake = stubs.ImportFake({'qutebrowser.browser.webengine': False}, monkeypatch)
    fake.patch()

    parsed = parser.parse_args([])
    args = qtargs.qt_args(parsed)
    assert args == [sys.argv[0]]


_XFAIL_FUTURE_QT = (
    pytest.mark.xfail(
        utils.VersionNumber(6, 11) not in version.WebEngineVersions._CHROMIUM_VERSIONS,
        reason="Unknown security patch version for Qt 6.11 so far",
    ),
)


@pytest.mark.usefixtures('reduce_args')
class TestWebEngineArgs:

    @pytest.fixture(autouse=True)
    def ensure_webengine(self, monkeypatch):
        """Skip all tests if QtWebEngine is unavailable."""
        pytest.importorskip("qutebrowser.qt.webenginecore")

    @pytest.mark.parametrize("setting, values", qtargs._WEBENGINE_SETTINGS.items())
    def test_settings_exist(self, setting, values, configdata_init):
        option = configdata.DATA[setting]
        for value in values:
            option.typ.to_py(value)  # for validation

    @pytest.mark.parametrize('qt_version, debug_flag, expected', [
        # Enable with -D stack, do nothing without it.
        ('6.8.2', True, True),
        ('6.8.2', False, None),
    ])
    def test_in_process_stack_traces(self, monkeypatch, parser, version_patcher,
                                     qt_version, debug_flag, expected):
        version_patcher(qt_version)
        parsed = parser.parse_args(['--debug-flag', 'stack'] if debug_flag
                                   else [])
        args = qtargs.qt_args(parsed)

        if expected is None:
            assert '--disable-in-process-stack-traces' not in args
            assert '--enable-in-process-stack-traces' not in args
        elif expected:
            assert '--disable-in-process-stack-traces' not in args
            assert '--enable-in-process-stack-traces' in args
        else:
            assert '--disable-in-process-stack-traces' in args
            assert '--enable-in-process-stack-traces' not in args

    @pytest.mark.parametrize(
        'qt_version, value, has_arg',
        [
            ('6.8.0', 'auto', True),
            ('6.8.1', 'auto', True),
            ('6.8.2', 'auto', False),
            ('6.8.1', 'always', True),
            ('6.8.1', 'never', False),
            ('6.8.2', 'always', True),
        ],
    )
    def test_accelerated_2d_canvas(
        self,
        parser,
        version_patcher,
        config_stub,
        monkeypatch,
        qt_version,
        value,
        has_arg,
    ):
        version_patcher(qt_version)
        config_stub.val.qt.workarounds.disable_accelerated_2d_canvas = value

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        assert ('--disable-accelerated-2d-canvas' in args) == has_arg

    @pytest.mark.parametrize(
        "qt_version, value, has_arg",
        [
            # 6.8.5 is broken too, but commercial-only
            ("6.10.0", "always", True),
            ("6.10.0", "auto", False),
            ("6.10.1", "auto", True),
            ("6.10.1", "never", False),
            ("6.10.2", "always", True),
            ("6.10.2", "auto", False),
            pytest.param("6.11.0", "always", True, marks=_XFAIL_FUTURE_QT),
            pytest.param("6.11.0", "auto", False, marks=_XFAIL_FUTURE_QT),
        ],
    )
    def test_disable_accessibility(
        self,
        parser,
        version_patcher,
        config_stub,
        monkeypatch,
        qt_version,
        value,
        has_arg,
    ):
        version_patcher(qt_version)
        config_stub.val.qt.workarounds.disable_accessibility = value

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        assert ('--disable-renderer-accessibility' in args) == has_arg

    @pytest.mark.parametrize('flags, args', [
        ([], []),
        (['--debug-flag', 'chromium'], ['--enable-logging', '--v=1']),
        (['--debug-flag', 'wait-renderer-process'], ['--renderer-startup-dialog']),
    ])
    def test_chromium_flags(self, monkeypatch, parser, flags, args):
        parsed = parser.parse_args(flags)
        args = qtargs.qt_args(parsed)

        if args:
            for arg in args:
                assert arg in args
        else:
            assert '--enable-logging' not in args
            assert '--v=1' not in args
            assert '--renderer-startup-dialog' not in args

    @pytest.mark.parametrize('config, added', [
        ('none', False),
        ('qt-quick', False),
        ('software-opengl', False),
        ('chromium', True),
    ])
    def test_disable_gpu(self, config, added, config_stub, monkeypatch, parser):
        config_stub.val.qt.force_software_rendering = config
        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        assert ('--disable-gpu' in args) == added

    @pytest.mark.parametrize('policy, arg', [
        ('all-interfaces', None),

        ('default-public-and-private-interfaces',
         '--force-webrtc-ip-handling-policy='
         'default_public_and_private_interfaces'),

        ('default-public-interface-only',
         '--force-webrtc-ip-handling-policy='
         'default_public_interface_only'),

        ('disable-non-proxied-udp',
         '--force-webrtc-ip-handling-policy='
         'disable_non_proxied_udp'),
    ])
    def test_webrtc(self, config_stub, monkeypatch, parser, policy, arg):
        config_stub.val.content.webrtc_ip_handling_policy = policy

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        if arg is None:
            assert not any(a.startswith('--force-webrtc-ip-handling-policy=')
                           for a in args)
        else:
            assert arg in args

    @pytest.mark.parametrize('canvas_reading, added', [
        (True, False),  # canvas reading enabled
        (False, True),
    ])
    def test_canvas_reading(self, config_stub, parser, canvas_reading, added):
        config_stub.val.content.canvas_reading = canvas_reading
        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        assert ('--disable-reading-from-canvas' in args) == added

    @pytest.mark.parametrize('process_model, added', [
        ('process-per-site-instance', False),
        ('process-per-site', True),
        ('single-process', True),
    ])
    def test_process_model(self, config_stub, parser, process_model, added):
        config_stub.val.qt.chromium.process_model = process_model
        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        if added:
            assert '--' + process_model in args
        else:
            assert '--process-per-site' not in args
            assert '--single-process' not in args
            assert '--process-per-site-instance' not in args
            assert '--process-per-tab' not in args

    @pytest.mark.parametrize('low_end_device_mode, arg', [
        ('auto', None),
        ('always', '--enable-low-end-device-mode'),
        ('never', '--disable-low-end-device-mode'),
    ])
    def test_low_end_device_mode(self, config_stub, parser, low_end_device_mode, arg):
        config_stub.val.qt.chromium.low_end_device_mode = low_end_device_mode
        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        if arg is None:
            assert '--enable-low-end-device-mode' not in args
            assert '--disable-low-end-device-mode' not in args
        else:
            assert arg in args

    @pytest.mark.parametrize('sandboxing, arg', [
        ('enable-all', None),
        ('disable-seccomp-bpf', '--disable-seccomp-filter-sandbox'),
        ('disable-all', '--no-sandbox'),
    ])
    def test_sandboxing(self, config_stub, parser, sandboxing, arg):
        config_stub.val.qt.chromium.sandboxing = sandboxing
        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        remaining_flags = {
            '--no-sandbox',
            '--disable-seccomp-filter-sandbox',
        }
        if arg is not None:
            remaining_flags.remove(arg)

        if arg is not None:
            assert arg in args

        assert not set(args) & remaining_flags

    @pytest.mark.parametrize('bar, added', [
        # Overlay bar enabled
        ('overlay', True),
        # Overlay disabled
        ('when-searching', False),
        ('always', False),
        ('never', False),
    ])
    def test_overlay_scrollbar(self, config_stub, monkeypatch, parser,
                               bar, added):
        config_stub.val.scrolling.bar = bar

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        expected = 'WebRTCPipeWireCapturer' + (',OverlayScrollbar' if added else '')
        assert qtargs._ENABLE_FEATURES + expected in args

    @pytest.mark.parametrize('via_commandline', [True, False])
    @pytest.mark.parametrize('overlay, passed_features, expected_features', [
        (True,
         'CustomFeature',
         'CustomFeature,WebRTCPipeWireCapturer,OverlayScrollbar'),
        (True,
         'CustomFeature1,CustomFeature2',
         'CustomFeature1,CustomFeature2,WebRTCPipeWireCapturer,OverlayScrollbar'),
        (False,
         'CustomFeature',
         'CustomFeature,WebRTCPipeWireCapturer'),
    ])
    def test_overlay_features_flag(self, config_stub, parser,
                                   via_commandline, overlay, passed_features,
                                   expected_features):
        """If enable-features is already specified, we should combine both."""
        config_flag = qtargs._ENABLE_FEATURES.lstrip('-') + passed_features

        config_stub.val.scrolling.bar = 'overlay' if overlay else 'never'
        config_stub.val.qt.args = ([] if via_commandline else [config_flag])

        parsed = parser.parse_args(['--qt-flag', config_flag]
                                   if via_commandline else [])
        args = qtargs.qt_args(parsed)

        overlay_flag = qtargs._ENABLE_FEATURES + 'OverlayScrollbar'
        combined_flag = qtargs._ENABLE_FEATURES + expected_features

        enable_features_args = [
            arg for arg in args
            if arg.startswith(qtargs._ENABLE_FEATURES)
        ]
        assert len(enable_features_args) == 1
        assert combined_flag in args
        assert overlay_flag not in args

    @pytest.mark.parametrize('via_commandline', [True, False])
    @pytest.mark.parametrize('passed_features', [
        ['CustomFeature'],
        ['CustomFeature1', 'CustomFeature2'],
    ])
    def test_disable_features_passthrough(self, config_stub, parser,
                                          via_commandline, passed_features):
        flag = qtargs._DISABLE_FEATURES + ','.join(passed_features)

        config_flag = flag.lstrip('-')
        config_stub.val.qt.args = ([] if via_commandline else [config_flag])
        parsed = parser.parse_args(['--qt-flag', config_flag]
                                   if via_commandline else [])
        args = qtargs.qt_args(parsed)

        disable_features_args = [
            arg for arg in args
            if arg.startswith(qtargs._DISABLE_FEATURES)
        ]
        # DocumentPictureInPictureAPI is always disabled
        assert disable_features_args == [flag + ',DocumentPictureInPictureAPI']

    def test_blink_settings_passthrough(self, parser, config_stub):
        config_stub.val.colors.webpage.darkmode.enabled = True

        flag = qtargs._BLINK_SETTINGS + 'foo=bar'
        parsed = parser.parse_args(['--qt-flag', flag.lstrip('-')])
        args = qtargs.qt_args(parsed)

        blink_settings_args = [
            arg for arg in args
            if arg.startswith(qtargs._BLINK_SETTINGS)
        ]
        assert blink_settings_args == ['--blink-settings=foo=bar']

    @pytest.mark.parametrize('qt_version, disabled', [
        # Qt 6.8
        ('6.8.0', "DocumentPictureInPictureAPI"),
        ('6.8.1', "DocumentPictureInPictureAPI"),
        ('6.8.2', "DocumentPictureInPictureAPI"),
        ('6.8.3', "DocumentPictureInPictureAPI"),
        # Qt 6.9
        ('6.9.0', "DocumentPictureInPictureAPI,PermissionElement"),
        ('6.9.1', "DocumentPictureInPictureAPI,PermissionElement"),
        # Qt 6.10
        ('6.10.0', "DocumentPictureInPictureAPI,PermissionElement"),
        ('6.10.1', "DocumentPictureInPictureAPI"),
    ])
    def test_disable_feature_workaround(
        self, parser, version_patcher, qt_version, disabled
    ):
        version_patcher(qt_version)

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        disable_features_args = [
            arg for arg in args
            if arg.startswith(qtargs._DISABLE_FEATURES)
        ]

        expected = [f"--disable-features={disabled}"] if disabled else []
        assert disable_features_args == expected

    @pytest.mark.parametrize('enabled', [True, False])
    def test_media_keys(self, config_stub, parser, enabled):
        config_stub.val.input.media_keys = enabled

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        disable_features_args = [
            arg for arg in args
            if arg.startswith(qtargs._DISABLE_FEATURES)
        ]
        assert len(disable_features_args) == 1
        features = disable_features_args[0].split('=', maxsplit=1)[1].split(',')
        assert ('HardwareMediaKeyHandling' in features) != enabled

    def test_dark_mode_settings(self, config_stub, parser):
        config_stub.val.colors.webpage.darkmode.enabled = True

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)

        assert '--dark-mode-settings=ImagePolicy=2,ImageClassifierPolicy=0' in args
        assert not any(arg.startswith(qtargs._BLINK_SETTINGS) for arg in args)

    @pytest.mark.parametrize('value, has_arg', [
        ('always', True),
        ('auto', False),
        ('never', False),
    ])
    def test_experimental_web_platform_features(
        self, value, has_arg, parser, config_stub,
    ):
        config_stub.val.qt.chromium.experimental_web_platform_features = value

        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        assert ('--enable-experimental-web-platform-features' in args) == has_arg

    def test_webengine_args(self, parser):
        parsed = parser.parse_args([])
        args = qtargs.qt_args(parsed)
        assert args[1] == "--webEngineArgs"


class TestEnvVars:

    @pytest.mark.parametrize('config_opt, config_val, envvar, expected', [
        ('qt.force_software_rendering', 'software-opengl',
         'QT_XCB_FORCE_SOFTWARE_OPENGL', '1'),
        ('qt.force_software_rendering', 'qt-quick',
         'QT_QUICK_BACKEND', 'software'),
        ('qt.force_software_rendering', 'chromium',
         'QT_WEBENGINE_DISABLE_NOUVEAU_WORKAROUND', '1'),
        ('qt.force_platform', 'toaster', 'QT_QPA_PLATFORM', 'toaster'),
        ('qt.force_platformtheme', 'lxde', 'QT_QPA_PLATFORMTHEME', 'lxde'),
        ('window.hide_decoration', True,
         'QT_WAYLAND_DISABLE_WINDOWDECORATION', '1')
    ])
    def test_env_vars(self, monkeypatch, config_stub,
                      config_opt, config_val, envvar, expected):
        """Check settings which set an environment variable."""
        monkeypatch.setenv(envvar, '')  # to make sure it gets restored
        monkeypatch.delenv(envvar)

        config_stub.set_obj(config_opt, config_val)
        qtargs.init_envvars()

        assert os.environ[envvar] == expected

    @pytest.mark.parametrize('init_val, config_val', [
        (   # Test changing a set variable
            {'QT_SCALE_FACTOR': '2'},
            {'QT_SCALE_FACTOR': '4'},
        ),
        (   # Test setting an unset variable
            {'QT_SCALE_FACTOR': None},
            {'QT_SCALE_FACTOR': '3'},
        ),
        (   # Test unsetting a variable which is set
            {'QT_SCALE_FACTOR': '3'},
            {'QT_SCALE_FACTOR': None},
        ),
        (   # Test unsetting a variable which is unset
            {'QT_SCALE_FACTOR': None},
            {'QT_SCALE_FACTOR': None},
        ),
        (   # Test setting multiple variables
            {'QT_SCALE_FACTOR': '0', 'QT_PLUGIN_PATH': '/usr/bin', 'QT_NEWVAR': None},
            {'QT_SCALE_FACTOR': '3', 'QT_PLUGIN_PATH': '/tmp/', 'QT_NEWVAR': 'newval'},
        )
    ])
    def test_environ_settings(self, monkeypatch, config_stub,
                              init_val, config_val):
        """Test setting environment variables using qt.environ."""
        for var, val in init_val.items():
            if val is None:
                monkeypatch.setenv(var, '0')
                monkeypatch.delenv(var, raising=False)
            else:
                monkeypatch.setenv(var, val)

        config_stub.val.qt.environ = config_val
        qtargs.init_envvars()

        for var, result in config_val.items():
            if result is None:
                assert var not in os.environ
            else:
                assert os.environ[var] == result

    def test_highdpi(self, monkeypatch, config_stub):
        """Test HighDPI environment variables."""
        envvar = 'QT_ENABLE_HIGHDPI_SCALING'
        monkeypatch.setenv(envvar, '')  # to make sure it gets restored
        monkeypatch.delenv(envvar)

        config_stub.set_obj('qt.highdpi', True)
        qtargs.init_envvars()

        assert os.environ[envvar] == '1'

    @pytest.mark.parametrize('value, expected', [
        (None, None),
        ('', "''"),
        ('--xyz', "'--xyz'"),
    ])
    def test_qtwe_flags_warning(self, monkeypatch, config_stub, caplog,
                                value, expected):
        if value is None:
            monkeypatch.delenv('QTWEBENGINE_CHROMIUM_FLAGS', raising=False)
        else:
            monkeypatch.setenv('QTWEBENGINE_CHROMIUM_FLAGS', value)

        with caplog.at_level(logging.WARNING):
            qtargs.init_envvars()

        if expected is None:
            assert not caplog.messages
        else:
            assert len(caplog.messages) == 1
            msg = caplog.messages[0]
            assert msg.startswith(f'You have QTWEBENGINE_CHROMIUM_FLAGS={expected} set')
