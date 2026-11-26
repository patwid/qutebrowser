# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later


import pytest
QWebEngineSettings = pytest.importorskip("qutebrowser.qt.webenginecore").QWebEngineSettings

from qutebrowser.config import configdata
from qutebrowser.browser.webengine import darkmode


class TestSetting:

    @pytest.mark.parametrize("value, mapping, expected", [
        ("val", None, ("key", "val")),
        (5, None, ("key", "5")),
        (True, {True: "true"}, ("key", "true")),
        ("excluded", {"excluded": None}, None),
    ])
    def test_chromium_tuple(self, value, mapping, expected):
        setting = darkmode._Setting(option="opt", chromium_key="key", mapping=mapping)
        assert setting.chromium_tuple(value) == expected


@pytest.mark.parametrize('value, expected', [
    ("auto", []),
    (None, []),  # unset
    ("dark", [("preferredColorScheme", "0")]),
    ("light", [("preferredColorScheme", "1")]),
])
def test_colorscheme(config_stub, value, expected):
    if value is not None:
        config_stub.val.colors.webpage.preferred_color_scheme = value

    darkmode_settings = darkmode.settings(special_flags=[])
    assert darkmode_settings['blink-settings'] == expected


@pytest.mark.parametrize('settings, expected', [
    # Disabled
    ({}, {}),

    # Enabled without customization
    (
        {'enabled': True},
        {
            'dark-mode-settings': [
                ('ImagePolicy', '2'),
                ('ImageClassifierPolicy', '0'),
            ],
        },
    ),

    # Algorithm
    (
        {'enabled': True, 'algorithm': 'brightness-rgb'},
        {
            'dark-mode-settings': [
                ('InversionAlgorithm', '1'),
                ('ImagePolicy', '2'),
                ('ImageClassifierPolicy', '0'),
            ],
        },
    ),

    # Algorithm and threshold
    (
        {
            'enabled': True,
            'algorithm': 'brightness-rgb',
            'threshold.foreground': 100,
        },
        {
            'dark-mode-settings': [
                ('InversionAlgorithm', '1'),
                ('ImagePolicy', '2'),
                ('ForegroundBrightnessThreshold', '100'),
                ('ImageClassifierPolicy', '0'),
            ],
        },
    ),
])
def test_basics(config_stub, settings, expected):
    for k, v in settings.items():
        config_stub.set_obj('colors.webpage.darkmode.' + k, v)

    darkmode_settings = darkmode.settings(special_flags=[])
    assert darkmode_settings == expected


@pytest.mark.parametrize('setting, value, expected', [
    ('contrast', -0.5, [
        ('ImagePolicy', '2'),
        ('ContrastPercent', '-0.5'),
        ('ImageClassifierPolicy', '0'),
    ]),
    ('threshold.foreground', 100, [
        ('ImagePolicy', '2'),
        ('ForegroundBrightnessThreshold', '100'),
        ('ImageClassifierPolicy', '0'),
    ]),
    ('threshold.background', 100, [
        ('ImagePolicy', '2'),
        ('BackgroundBrightnessThreshold', '100'),
        ('ImageClassifierPolicy', '0'),
    ]),
    ('policy.images', 'always', [('ImagePolicy', '0')]),
    ('policy.images', 'never', [('ImagePolicy', '1')]),
    ('policy.images', 'smart', [
        ('ImagePolicy', '2'),
        ('ImageClassifierPolicy', '0'),
    ]),
    ('policy.images', 'smart-simple', [
        ('ImagePolicy', '2'),
        ('ImageClassifierPolicy', '1'),
    ]),
])
def test_customization(config_stub, setting, value, expected):
    config_stub.val.colors.webpage.darkmode.enabled = True
    config_stub.set_obj('colors.webpage.darkmode.' + setting, value)

    darkmode_settings = darkmode.settings(special_flags=[])
    assert 'blink-settings' not in darkmode_settings
    assert darkmode_settings['dark-mode-settings'] == expected


@pytest.mark.parametrize('flag, expected', [
    ('--blink-settings=key=value', [('key', 'value')]),
    ('--blink-settings=key=equal=rights', [('key', 'equal=rights')]),
    ('--blink-settings=one=1,two=2', [('one', '1'), ('two', '2')]),
    ('--enable-features=feat', []),
])
def test_pass_through_existing_settings(config_stub, flag, expected):
    config_stub.val.colors.webpage.darkmode.enabled = True
    settings = darkmode.settings(special_flags=[flag])
    assert settings['blink-settings'] == expected


def test_options(configdata_init):
    """Make sure all darkmode options have the right attributes set."""
    for name, opt in configdata.DATA.items():
        if not name.startswith('colors.webpage.darkmode.'):
            continue

        if name != 'colors.webpage.darkmode.enabled':
            assert not opt.supports_pattern, name
            assert opt.restart, name
