# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utilities to show various version information."""

import re
import sys
import glob
import os.path
import platform
import subprocess
import importlib
import pathlib
import configparser
import enum
import datetime
import getpass
import functools
import dataclasses
import importlib.metadata
from typing import Any
from collections.abc import Mapping, Sequence

from qutebrowser.qt.core import PYQT_VERSION_STR
from qutebrowser.qt.network import QSslSocket
from qutebrowser.qt.gui import QOpenGLContext, QOffscreenSurface
from qutebrowser.qt.opengl import QOpenGLVersionProfile
from qutebrowser.qt.widgets import QApplication


import qutebrowser
from qutebrowser.utils import (log, utils, standarddir, message, resources,
                               qtutils)
from qutebrowser.misc import objects, earlyinit, sql, httpclient, pastebin, wmname
from qutebrowser.browser import pdfjs
from qutebrowser.config import config

_LOGO = r'''
         ______     ,,
    ,.-"`      | ,-` |
  .^           ||    |
 /    ,-*^|    ||    |
;    /    |    ||    ;-*```^*.
;   ;     |    |;,-*`         \
|   |     |  ,-*`    ,-"""\    \
|    \   ,-"`    ,-^`|     \    |
 \    `^^    ,-;|    |     ;    |
  *;     ,-*`  ||    |     /   ;;
    `^^`` |    ||    |   ,^    /
          |    ||    `^^`    ,^
          |  _,"|        _,-"
          -*`   ****"""``

'''


@dataclasses.dataclass
class DistributionInfo:

    """Information about the running distribution."""

    id: str | None
    parsed: 'Distribution'
    pretty: str


pastebin_url: str | None = None


class Distribution(enum.Enum):

    """A known Linux distribution.

    Usually lines up with ID=... in /etc/os-release.
    """

    unknown = enum.auto()
    ubuntu = enum.auto()
    debian = enum.auto()
    void = enum.auto()
    arch = enum.auto()  # includes rolling-release derivatives
    gentoo = enum.auto()  # includes funtoo
    fedora = enum.auto()
    opensuse = enum.auto()
    linuxmint = enum.auto()
    manjaro = enum.auto()
    kde_flatpak = enum.auto()  # org.kde.Platform
    neon = enum.auto()
    nixos = enum.auto()
    alpine = enum.auto()
    solus = enum.auto()


def _parse_os_release() -> dict[str, str] | None:
    """Parse an /etc/os-release file."""
    filename = os.environ.get('QUTE_FAKE_OS_RELEASE', '/etc/os-release')
    info = {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if (not line) or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split("=", maxsplit=1)
                info[k] = v.strip('"')
    except (OSError, UnicodeDecodeError):
        return None

    return info


def distribution() -> DistributionInfo | None:
    """Get some information about the running Linux distribution.

    Returns:
        A DistributionInfo object, or None if no info could be determined.
            parsed: A Distribution enum member
            pretty: Always a string (might be "Unknown")
    """
    info = _parse_os_release()
    if info is None:
        return None

    pretty = info.get('PRETTY_NAME', None)
    if pretty in ['Linux', None]:  # Funtoo has PRETTY_NAME=Linux
        pretty = info.get('NAME', 'Unknown')
    assert pretty is not None

    dist_id = info.get('ID', None)
    id_mappings = {
        'funtoo': 'gentoo',  # does not have ID_LIKE=gentoo
        'artix': 'arch',
        'org.kde.Platform': 'kde_flatpak',
    }

    ids = []
    if dist_id is not None:
        ids.append(id_mappings.get(dist_id, dist_id))
    if 'ID_LIKE' in info:
        ids.extend(info['ID_LIKE'].split())

    parsed = Distribution.unknown
    for cur_id in ids:
        try:
            parsed = Distribution[cur_id]
        except KeyError:
            pass
        else:
            break

    return DistributionInfo(parsed=parsed, pretty=pretty, id=dist_id)


def is_flatpak() -> bool:
    """Whether qutebrowser is running via Flatpak.

    If packaged via Flatpak, the environment is has restricted access to the host
    system.
    """
    return flatpak_id() is not None


_FLATPAK_INFO_PATH = '/.flatpak-info'


def flatpak_id() -> str | None:
    """Get the ID of the currently running Flatpak (or None if outside of Flatpak)."""
    if 'FLATPAK_ID' in os.environ:
        return os.environ['FLATPAK_ID']

    # 'FLATPAK_ID' was only added in Flatpak 1.2.0:
    # https://lists.freedesktop.org/archives/flatpak/2019-January/001464.html
    # but e.g. Ubuntu 18.04 ships 1.0.9.
    info_file = pathlib.Path(_FLATPAK_INFO_PATH)
    if not info_file.exists():
        return None

    parser = configparser.ConfigParser()
    parser.read(info_file)
    return parser['Application']['name']


def _git_str() -> str | None:
    """Try to find out git version.

    Return:
        string containing the git commit ID.
        None if there was an error or we're not in a git repo.
    """
    # First try via subprocess if possible
    commit = None
    if not hasattr(sys, "frozen"):
        try:
            gitpath = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   os.path.pardir, os.path.pardir)
        except (NameError, OSError):
            log.misc.exception("Error while getting git path")
        else:
            commit = _git_str_subprocess(gitpath)
    if commit is not None:
        return commit
    # If that fails, check the git-commit-id file.
    try:
        return resources.read_file('git-commit-id')
    except (OSError, ImportError):
        return None


def _call_git(gitpath: str, *args: str) -> str:
    """Call a git subprocess."""
    return subprocess.run(
        ['git'] + list(args),
        cwd=gitpath, check=True,
        stdout=subprocess.PIPE).stdout.decode('UTF-8').strip()


def _git_str_subprocess(gitpath: str) -> str | None:
    """Try to get the git commit ID and timestamp by calling git.

    Args:
        gitpath: The path where the .git folder is.

    Return:
        The ID/timestamp on success, None on failure.
    """
    if not os.path.isdir(os.path.join(gitpath, ".git")):
        return None
    try:
        # https://stackoverflow.com/questions/21017300/21017394#21017394
        commit_hash = _call_git(gitpath, 'describe', '--match=NeVeRmAtCh',
                                '--always', '--dirty')
        date = _call_git(gitpath, 'show', '-s', '--format=%ci', 'HEAD')
        branch = _call_git(gitpath, 'rev-parse', '--abbrev-ref', 'HEAD')
        return '{} on {} ({})'.format(commit_hash, branch, date)
    except (subprocess.CalledProcessError, OSError):
        return None


def _release_info() -> Sequence[tuple[str, str]]:
    """Try to gather distribution release information.

    Return:
        list of (filename, content) tuples.
    """
    blacklisted = ['ANSI_COLOR=', 'HOME_URL=', 'SUPPORT_URL=',
                   'BUG_REPORT_URL=']
    data = []
    for fn in glob.glob("/etc/*-release"):
        lines = []
        try:
            with open(fn, 'r', encoding='utf-8') as f:
                for line in f.read().strip().splitlines():
                    if not any(line.startswith(bl) for bl in blacklisted):
                        lines.append(line)

                if lines:
                    data.append((fn, '\n'.join(lines)))
        except OSError:
            log.misc.exception("Error while reading {}.".format(fn))
    return data


class ModuleInfo:

    """Class to query version information of qutebrowser dependencies.

    Attributes:
        name: Name of the module as it is imported.
        _version_attributes:
            Sequence of attribute names belonging to the module which may hold
            version information.
        min_version: Minimum version of this module which qutebrowser can use.
        _installed: Is the module installed? Determined at runtime.
        _version: Version of the module. Determined at runtime.
        _initialized:
            Set to `True` if the `self._installed` and `self._version`
            attributes have been set.
    """

    def __init__(
        self,
        name: str,
        version_attributes: Sequence[str],
        min_version: str | None = None
    ):
        self.name = name
        self._version_attributes = version_attributes
        self.min_version = min_version
        self._installed = False
        self._version: str | None = None
        self._initialized = False

    def _reset_cache(self) -> None:
        """Reset the version cache.

        It is necessary to call this method in unit tests that mock a module's
        version number.
        """
        self._installed = False
        self._version = None
        self._initialized = False

    def _initialize_info(self) -> None:
        """Import module and set `self.installed` and `self.version`."""
        try:
            module = importlib.import_module(self.name)
        except (ImportError, ValueError):
            self._installed = False
            return

        self._installed = True

        for attribute_name in self._version_attributes:
            if hasattr(module, attribute_name):
                version = getattr(module, attribute_name)
                assert isinstance(version, (str, float))
                self._version = str(version)
                break

        if self._version is None:
            try:
                self._version = importlib.metadata.version(self.name)
            except importlib.metadata.PackageNotFoundError:
                log.misc.debug(f"{self.name} not found")
                self._version = None

        self._initialized = True

    def get_version(self) -> str | None:
        """Finds the module version if it exists."""
        if not self._initialized:
            self._initialize_info()
        return self._version

    def is_installed(self) -> bool:
        """Checks whether the module is installed."""
        if not self._initialized:
            self._initialize_info()
        return self._installed

    def is_outdated(self) -> bool | None:
        """Checks whether the module is outdated.

        Return:
            A boolean when the version and minimum version are both defined.
            Otherwise `None`.
        """
        version = self.get_version()
        if (
            not self.is_installed()
            or version is None
            or self.min_version is None
        ):
            return None
        return version < self.min_version

    def is_usable(self) -> bool:
        """Whether the module is both installed and not outdated."""
        return self.is_installed() and not self.is_outdated()

    def __str__(self) -> str:
        if not self.is_installed():
            return f'{self.name}: no'

        version = self.get_version()
        if version is None:
            return f'{self.name}: unknown'

        text = f'{self.name}: {version}'
        if self.is_outdated():
            text += f" (< {self.min_version}, outdated)"
        return text


def _create_module_info() -> dict[str, ModuleInfo]:
    packages = [
        ('jinja2', []),
        ('pygments', ['__version__']),
        ('yaml', ['__version__']),
        ('adblock', ['__version__'], "0.3.2"),
    ]

    packages += [
        ('PyQt6.QtWebEngineCore', ['PYQT_WEBENGINE_VERSION_STR']),
        ('PyQt6.sip', ['SIP_VERSION_STR']),
    ]

    # Mypy doesn't understand this. See https://github.com/python/mypy/issues/9706
    return {
        name: ModuleInfo(name, *args)  # type: ignore[arg-type, misc]
        for (name, *args) in packages
    }


MODULE_INFO: Mapping[str, ModuleInfo] = _create_module_info()


def _module_versions() -> Sequence[str]:
    """Get versions of optional modules.

    Return:
        A list of lines with version info.
    """
    return [str(mod_info) for mod_info in MODULE_INFO.values()]


def _path_info() -> Mapping[str, str]:
    """Get info about important path names.

    Return:
        A dictionary of descriptive to actual path names.
    """
    info = {
        'config': standarddir.config(),
        'data': standarddir.data(),
        'cache': standarddir.cache(),
        'runtime': standarddir.runtime(),
    }
    if standarddir.data() != standarddir.data(system=True):
        info['system data'] = standarddir.data(system=True)
    return info


def _os_info() -> Sequence[str]:
    """Get operating system info.

    Return:
        A list of lines with version info.
    """
    lines = ['OS Version: ']
    for (fn, data) in _release_info():
        lines += ['', '--- {} ---'.format(fn), data]
    return lines


def _pdfjs_version() -> str:
    """Get the pdf.js version.

    Return:
        A string with the version number.
    """
    try:
        pdfjs_file, file_path = pdfjs.get_pdfjs_res_and_path(pdfjs.get_pdfjs_js_path())
    except pdfjs.PDFJSNotFound:
        return 'no'
    else:
        pdfjs_file = pdfjs_file.decode('utf-8')
        version_re = re.compile(
            r"""^ *(PDFJS\.version|(var|const|\*) pdfjsVersion) = ['"]?(?P<version>[^'"\n]+)['"]?;?$""",
            re.MULTILINE)

        match = version_re.search(pdfjs_file)
        pdfjs_version = 'unknown' if not match else match.group('version')
        if file_path is None:
            file_path = 'bundled'

        return '{} ({})'.format(pdfjs_version, file_path)


@dataclasses.dataclass
class WebEngineVersions:

    """Version numbers for QtWebEngine and the underlying Chromium."""

    webengine: utils.VersionNumber
    chromium: str | None
    source: str
    chromium_security: str | None = None
    chromium_major: int | None = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Set the major Chromium version."""
        if self.chromium is None:
            self.chromium_major = None
        else:
            self.chromium_major = int(self.chromium.split('.')[0])

    def __str__(self) -> str:
        lines = [f'QtWebEngine {self.webengine}']
        if self.chromium is not None:
            lines.append(f'  based on Chromium {self.chromium}')
        if self.chromium_security is not None:
            lines.append(f'  with security patches up to {self.chromium_security} (plus any distribution patches)')
        lines.append(f'  (source: {self.source})')
        return "\n".join(lines)


def qtwebengine_versions() -> WebEngineVersions:
    """Get the QtWebEngine and Chromium version numbers.

    This uses Qt's API, which doesn't need QtWebEngine to be initialized.
    """
    from qutebrowser.qt.webenginecore import (
        qWebEngineVersion,
        qWebEngineChromiumVersion,
        qWebEngineChromiumSecurityPatchVersion,
    )

    qtwe_version = qWebEngineVersion()
    assert qtwe_version is not None
    return WebEngineVersions(
        webengine=utils.VersionNumber.parse(qtwe_version),
        chromium=qWebEngineChromiumVersion(),
        chromium_security=qWebEngineChromiumSecurityPatchVersion(),
        source='api',
    )


def _webengine_extensions() -> Sequence[str]:
    """Get a list of WebExtensions enabled in QtWebEngine."""
    from qutebrowser.browser.webengine import webenginesettings
    lines = ["WebExtensions:"]

    if webenginesettings.default_profile:
        profile = webenginesettings.default_profile
    elif "avoid-chromium-init" in objects.debug_flags:
        lines[0] += " unknown (avoiding init)"
        return lines
    else:
        profile = webenginesettings.default_qt_profile()

    ext_manager = profile.extensionManager()
    assert ext_manager is not None  # mypy

    if not ext_manager.extensions():
        lines[0] += " none"

    for info in ext_manager.extensions():
        tags = [
            ("[x]" if info.isEnabled() else "[ ]") + " enabled",
            ("[x]" if info.isLoaded() else "[ ]") + " loaded",
            ("[x]" if info.isInstalled() else "[ ]") + " installed",
        ]
        lines.append(f"  {info.name()} ({info.id()})")
        lines.append(f"  {'  '.join(tags)}")
        lines.append(f"  {info.path()}")
        url = info.actionPopupUrl()
        if url.isValid():
            lines.append(f"  {url.toDisplayString()}")
        lines.append("")

    return lines


def _uptime() -> datetime.timedelta:
    time_delta = datetime.datetime.now() - objects.qapp.launch_time
    # Round off microseconds
    time_delta -= datetime.timedelta(microseconds=time_delta.microseconds)
    return time_delta


def _autoconfig_loaded() -> str:
    return "yes" if config.instance.yaml_loaded else "no"


def _config_py_loaded() -> str:
    if config.instance.config_py_loaded:
        return "{} has been loaded".format(standarddir.config_py())
    else:
        return "no config.py was loaded"


def version_info() -> str:
    """Return a string with various version information."""
    lines = _LOGO.lstrip('\n').splitlines()

    lines.append("qutebrowser v{}".format(qutebrowser.__version__))
    gitver = _git_str()
    if gitver is not None:
        lines.append("Git commit: {}".format(gitver))

    lines.append('Backend: {}'.format(qtwebengine_versions()))
    lines.append('Qt: {}'.format(earlyinit.qt_version()))

    lines += [
        '',
        '{}: {}'.format(platform.python_implementation(),
                        platform.python_version()),
        'PyQt: {}'.format(PYQT_VERSION_STR),
        '',
    ]

    lines += _module_versions()

    lines += [
        'pdf.js: {}'.format(_pdfjs_version()),
        'sqlite: {}'.format(sql.version()),
        'QtNetwork SSL: {}\n'.format(QSslSocket.sslLibraryVersionString()
                                     if QSslSocket.supportsSsl() else 'no'),
    ]

    lines += _webengine_extensions()

    if objects.qapp:
        style = objects.qapp.style()
        assert style is not None
        metaobj = style.metaObject()
        assert metaobj is not None
        lines.append('Style: {}'.format(metaobj.className()))
        lines.append('Qt Platform: {}'.format(gui_platform_info()))
        lines.append('OpenGL: {}'.format(opengl_info()))

    importpath = os.path.dirname(os.path.abspath(qutebrowser.__file__))

    lines += [
        'Platform: {}, {}'.format(platform.platform(),
                                  platform.architecture()[0]),
    ]
    dist = distribution()
    if dist is not None:
        lines += [
            'Linux distribution: {} ({})'.format(dist.pretty, dist.parsed.name)
        ]

    lines += [
        'Frozen: {}'.format(hasattr(sys, 'frozen')),
        "Imported from {}".format(importpath),
        "Using Python from {}".format(sys.executable),
        "Qt library executable path: {}, data path: {}".format(
            qtutils.library_path(qtutils.LibraryPath.library_executables),
            qtutils.library_path(qtutils.LibraryPath.data),
        )
    ]

    if not dist or dist.parsed == Distribution.unknown:
        lines += _os_info()

    lines += [
        '',
        'Paths:',
    ]
    for name, path in sorted(_path_info().items()):
        lines += ['{}: {}'.format(name, path)]

    lines += [
        '',
        'Autoconfig loaded: {}'.format(_autoconfig_loaded()),
        'Config.py: {}'.format(_config_py_loaded()),
        'Uptime: {}'.format(_uptime())
    ]

    return '\n'.join(lines)


@dataclasses.dataclass
class OpenGLInfo:

    """Information about the OpenGL setup in use."""

    # If we're using OpenGL ES. If so, no further information is available.
    gles: bool = False

    # The name of the vendor. Examples:
    # - nouveau
    # - "Intel Open Source Technology Center", "Intel", "Intel Inc."
    vendor: str | None = None

    # The OpenGL version as a string. See tests for examples.
    version_str: str | None = None

    # The parsed version as a (major, minor) tuple of ints
    version: tuple[int, ...] | None = None

    # The vendor specific information following the version number
    vendor_specific: str | None = None

    def __str__(self) -> str:
        if self.gles:
            return 'OpenGL ES'
        return '{}, {}'.format(self.vendor, self.version_str)

    @classmethod
    def parse(cls, *, vendor: str, version: str) -> 'OpenGLInfo':
        """Parse OpenGL version info from a string.

        The arguments should be the strings returned by OpenGL for GL_VENDOR
        and GL_VERSION, respectively.

        According to the OpenGL reference, the version string should have the
        following format:

        <major>.<minor>[.<release>] <vendor-specific info>
        """
        if ' ' not in version:
            log.misc.warning("Failed to parse OpenGL version (missing space): "
                             "{}".format(version))
            return cls(vendor=vendor, version_str=version)

        num_str, vendor_specific = version.split(' ', maxsplit=1)

        try:
            parsed_version = tuple(int(i) for i in num_str.split('.'))
        except ValueError:
            log.misc.warning("Failed to parse OpenGL version (parsing int): "
                             "{}".format(version))
            return cls(vendor=vendor, version_str=version)

        return cls(vendor=vendor, version_str=version,
                   version=parsed_version, vendor_specific=vendor_specific)


@functools.lru_cache(maxsize=1)
def opengl_info() -> OpenGLInfo | None:  # pragma: no cover
    """Get the OpenGL vendor used."""
    assert QApplication.instance()

    override = os.environ.get('QUTE_FAKE_OPENGL')
    if override is not None:
        log.init.debug("Using override {}".format(override))
        vendor, version = override.split(', ', maxsplit=1)
        return OpenGLInfo.parse(vendor=vendor, version=version)

    old_context: QOpenGLContext | None = QOpenGLContext.currentContext()
    old_surface = None if old_context is None else old_context.surface()

    surface = QOffscreenSurface()
    surface.create()

    ctx = QOpenGLContext()
    ok = ctx.create()
    if not ok:
        log.init.debug("Creating context failed!")
        return None

    ok = ctx.makeCurrent(surface)
    if not ok:
        log.init.debug("Making context current failed!")
        return None

    try:
        if ctx.isOpenGLES():
            # Can't use versionFunctions there
            return OpenGLInfo(gles=True)

        vp = QOpenGLVersionProfile()
        vp.setVersion(2, 0)

        try:
            from qutebrowser.qt.opengl import QOpenGLVersionFunctionsFactory
            vf: Any = QOpenGLVersionFunctionsFactory.get(vp, ctx)
        except ImportError as e:
            log.init.debug("Importing version functions failed: {}".format(e))
            return None

        if vf is None:
            log.init.debug("Getting version functions failed!")
            return None

        # FIXME:mypy PyQt6-stubs issue?
        vendor = vf.glGetString(vf.GL_VENDOR)
        version = vf.glGetString(vf.GL_VERSION)

        return OpenGLInfo.parse(vendor=vendor, version=version)
    finally:
        ctx.doneCurrent()
        if old_context and old_surface:
            old_context.makeCurrent(old_surface)


def gui_platform_info() -> str:
    """Get the Qt GUI platform name, optionally with the WM/compositor name."""
    info = objects.qapp.platformName()
    try:
        if info == "xcb":
            info += f" ({wmname.x11_wm_name()})"
        elif info in ["wayland", "wayland-egl"]:
            info += f" ({wmname.wayland_compositor_name()})"
    except wmname.Error as e:
        info += f" (Error: {e})"
    return info


def pastebin_version(pbclient: pastebin.PastebinClient | None = None) -> None:
    """Pastebin the version and log the url to messages."""
    def _yank_url(url: str) -> None:
        utils.set_clipboard(url)
        message.info("Version url {} yanked to clipboard.".format(url))

    def _on_paste_version_success(url: str) -> None:
        assert pbclient is not None
        global pastebin_url
        url = url.strip()
        _yank_url(url)
        pbclient.deleteLater()
        pastebin_url = url

    def _on_paste_version_err(text: str) -> None:
        assert pbclient is not None
        message.error("Failed to pastebin version"
                      " info: {}".format(text))
        pbclient.deleteLater()

    if pastebin_url:
        _yank_url(pastebin_url)
        return

    app = QApplication.instance()
    http_client = httpclient.HTTPClient()

    misc_api = pastebin.PastebinClient.MISC_API_URL
    pbclient = pbclient or pastebin.PastebinClient(http_client, parent=app,
                                                   api_url=misc_api)

    pbclient.success.connect(_on_paste_version_success)
    pbclient.error.connect(_on_paste_version_err)

    pbclient.paste(getpass.getuser(),
                   "qute version info {}".format(qutebrowser.__version__),
                   version_info(),
                   private=True)
