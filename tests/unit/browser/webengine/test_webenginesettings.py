# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later


import pytest

QtWebEngineCore = pytest.importorskip('qutebrowser.qt.webenginecore')
QWebEngineProfile = QtWebEngineCore.QWebEngineProfile
QWebEngineSettings = QtWebEngineCore.QWebEngineSettings

from qutebrowser.qt.core import QUrl

from qutebrowser.browser.webengine import webenginesettings
from qutebrowser.config import configdata
from qutebrowser.utils import urlmatch


@pytest.fixture
def settings(default_profile):
    wrapper = webenginesettings._SettingsWrapper()
    return webenginesettings.WebEngineSettings(wrapper)


@pytest.fixture
def global_settings(monkeypatch, settings):
    settings.init_settings()
    monkeypatch.setattr(webenginesettings, '_global_settings', settings)


@pytest.fixture
def default_profile(monkeypatch):
    """A profile to use which is set as default_profile.

    Note we use a "private" profile here to avoid actually storing data during tests.
    """
    profile = QtWebEngineCore.QWebEngineProfile()
    profile.setter = webenginesettings.ProfileSetter(profile)
    monkeypatch.setattr(profile, 'isOffTheRecord', lambda: False)
    monkeypatch.setattr(webenginesettings, 'default_profile', profile)
    return profile


@pytest.fixture
def private_profile(monkeypatch):
    """A profile to use which is set as private_profile."""
    profile = QtWebEngineCore.QWebEngineProfile()
    profile.setter = webenginesettings.ProfileSetter(profile)
    monkeypatch.setattr(webenginesettings, 'private_profile', profile)
    return profile


@pytest.mark.parametrize("setting, value, getter, expected", [
    # attribute
    (
        "content.images", False,
        lambda settings:
            settings.testAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages),
        False,
    ),
    # font size
    (
        "fonts.web.size.default", 23,
        lambda settings:
            settings.fontSize(QWebEngineSettings.FontSize.DefaultFontSize),
        23,
    ),
    # font family
    (
        "fonts.web.family.standard", "Comic Sans MS",
        lambda settings:
            settings.fontFamily(QWebEngineSettings.FontFamily.StandardFont),
        "Comic Sans MS",
    ),
    # encoding
    (
        "content.default_encoding", "utf-16",
        lambda settings: settings.defaultTextEncoding(),
        "utf-16",
    ),
    # unknown URL scheme policy
    (
        "content.unknown_url_scheme_policy", "allow-all",
        lambda settings: settings.unknownUrlSchemePolicy(),
        QWebEngineSettings.UnknownUrlSchemePolicy.AllowAllUnknownUrlSchemes,
    ),
    # JS clipboard
    (
        "content.javascript.clipboard", "access",
        lambda settings: settings.testAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard),
        True,
    ),
])
def test_initial_settings(settings, config_stub, default_profile,
                          setting, value, getter, expected):
    """Make sure initial setting values are applied correctly."""
    qt_settings = default_profile.settings()
    initial = getter(qt_settings)
    assert initial != expected  # no point in testing for the Qt default

    config_stub.set_obj(setting, value)
    settings.init_settings()

    actual = getter(qt_settings)
    assert actual == expected


@pytest.mark.parametrize("pdf_viewer, plugins, expected_viewer, expected_plugins", [
    (False, False, False, False),
    (False, True, False, True),
    # The viewer only works with plugins
    (True, False, True, True),
    (True, True, True, True),
])
def test_pdf_viewer(config_stub, default_profile, pdf_viewer, plugins,
                    expected_viewer, expected_plugins):
    qt_settings = default_profile.settings()
    settings = webenginesettings.WebEngineSettings(qt_settings)
    config_stub.val.content.pdf_viewer = pdf_viewer
    config_stub.val.content.plugins = plugins
    settings.init_settings()

    attribute = QWebEngineSettings.WebAttribute
    assert qt_settings.testAttribute(attribute.PdfViewerEnabled) == expected_viewer
    assert qt_settings.testAttribute(attribute.PluginsEnabled) == expected_plugins


def test_pdf_viewer_toggled(config_stub, default_profile):
    """Plugins follow the PDF viewer being turned on and off again."""
    qt_settings = default_profile.settings()
    settings = webenginesettings.WebEngineSettings(qt_settings)
    settings.init_settings()
    attribute = QWebEngineSettings.WebAttribute
    assert not qt_settings.testAttribute(attribute.PluginsEnabled)

    config_stub.val.content.pdf_viewer = True
    settings.update_setting('content.pdf_viewer')
    assert qt_settings.testAttribute(attribute.PdfViewerEnabled)
    assert qt_settings.testAttribute(attribute.PluginsEnabled)

    config_stub.val.content.pdf_viewer = False
    settings.update_setting('content.pdf_viewer')
    assert not qt_settings.testAttribute(attribute.PdfViewerEnabled)
    assert not qt_settings.testAttribute(attribute.PluginsEnabled)


def test_pdf_viewer_for_url(config_stub, default_profile):
    """Plugins being turned off for a URL don't turn off the PDF viewer."""
    qt_settings = default_profile.settings()
    settings = webenginesettings.WebEngineSettings(qt_settings)
    config_stub.val.content.pdf_viewer = True
    config_stub.set_str("content.plugins", "false",
                        pattern=urlmatch.UrlPattern("*://example.com/*"))
    settings.init_settings()
    settings.update_for_url(QUrl("https://example.com/test.pdf"))

    attribute = QWebEngineSettings.WebAttribute
    assert qt_settings.testAttribute(attribute.PluginsEnabled)


def test_big_cache_size(config_stub, default_profile):
    """Make sure a too big cache size is handled correctly."""
    config_stub.val.content.cache.size = 2 ** 63 - 1
    default_profile.setter.set_http_cache_size()
    assert default_profile.httpCacheMaximumSize() == 2 ** 31 - 1


def test_parsed_user_agent(qapp):
    webenginesettings.init_user_agent()
    parsed = webenginesettings.parsed_user_agent
    assert parsed is not None
    assert parsed.upstream_browser_key == 'Chrome'
    assert parsed.qt_key == 'QtWebEngine'
    assert not parsed.upstream_browser_version.endswith(".0.0.0")
    assert parsed.upstream_browser_version_short.endswith(".0.0.0")


CHROME_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) {} Safari/537.36")
DEFAULT_BRANDS = {'Chromium': '140.0.7339.264', 'Not=A?Brand': '24.0.0.0'}


@pytest.mark.parametrize("user_agent, expected", [
    # Same Chrome version as QtWebEngine
    (
        CHROME_UA.format("Chrome/140.0.0.0"),
        (
            {
                'Chromium': '140.0.7339.264',
                'Google Chrome': '140.0.7339.264',
                'Not=A?Brand': '24.0.0.0',
            },
            '140.0.7339.264',
        ),
    ),
    # Claiming a newer Chrome
    (
        CHROME_UA.format("Chrome/150"),
        (
            {
                'Chromium': '150.0.0.0',
                'Google Chrome': '150.0.0.0',
                'Not=A?Brand': '24.0.0.0',
            },
            '150.0.0.0',
        ),
    ),
    # Not claiming to be Chrome
    (CHROME_UA.format("QtWebEngine/6.140.0 Chrome/140.0.0.0"), None),
    (CHROME_UA.format("Chrome/140.0.0.0 Edg/140.0.0.0"), None),
    (CHROME_UA.format("Chrome/unknown"), None),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0", None),
    ("qutebrowser", None),
])
def test_client_hints_for_user_agent(user_agent, expected):
    hints = webenginesettings._client_hints_for_user_agent(
        user_agent, DEFAULT_BRANDS)
    assert hints == expected


def test_client_hints_no_chromium_brand():
    hints = webenginesettings._client_hints_for_user_agent(
        CHROME_UA.format("Chrome/140.0.0.0"), {'Not=A?Brand': '24.0.0.0'})
    assert hints is None


def test_client_hints_follow_user_agent(config_stub, monkeypatch, global_settings,
                                        default_profile, private_profile):
    """Client hints should claim to be Chrome iff the user agent does."""
    webenginesettings.init_user_agent()
    hints = default_profile.clientHints()
    default_brands = dict(hints.fullVersionList())
    default_full_version = hints.fullVersion()
    assert 'Google Chrome' not in default_brands

    config_stub.val.content.headers.user_agent = CHROME_UA.format("Chrome/1234.0.0.0")
    webenginesettings._update_settings('content.headers.user_agent')
    for profile in [default_profile, private_profile]:
        hints = profile.clientHints()
        assert hints.fullVersionList()['Google Chrome'] == '1234.0.0.0'
        assert hints.fullVersionList()['Chromium'] == '1234.0.0.0'
        assert hints.fullVersion() == '1234.0.0.0'

    config_stub.val.content.headers.user_agent = "qutebrowser"
    webenginesettings._update_settings('content.headers.user_agent')
    for profile in [default_profile, private_profile]:
        hints = profile.clientHints()
        assert hints.fullVersionList() == default_brands
        assert hints.fullVersion() == default_full_version


def test_profile_setter_settings(private_profile, configdata_init):
    for setting in private_profile.setter._name_to_method:
        assert setting in set(configdata.DATA)
