# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Functions related to the Brave adblocker."""

import io
import time
import logging
import pathlib
import functools
import dataclasses
import contextlib
import subprocess
from typing import Optional, IO
from collections.abc import Iterator

from qutebrowser.qt.core import QUrl

from qutebrowser.api import (
    hook,
    config,
    message,
    interceptor,
    apitypes,
    qtutils,
)
from qutebrowser.api.interceptor import ResourceType
from qutebrowser.components.utils import blockutils
from qutebrowser.utils import version  # FIXME: Move needed parts into api namespace?
from qutebrowser.utils import usertypes

try:
    import adblock
except ImportError:
    adblock = None  # type: ignore[assignment]

logger = logging.getLogger("network")
ad_blocker: Optional["BraveAdBlocker"] = None

# How long to wait after startup until outdated lists are updated, and how
# often to check for outdated lists afterwards (in ms).
_AUTO_UPDATE_STARTUP_DELAY = 10 * 1000
_AUTO_UPDATE_CHECK_INTERVAL = 24 * 60 * 60 * 1000


def _possibly_show_missing_dependency_warning() -> None:
    """Show a warning if the optional adblock dependency is not usable."""
    adblock_info = version.MODULE_INFO["adblock"]

    if adblock_info.is_outdated():
        message.warning(
            f"Installed version {adblock_info.get_version()} of the 'adblock' "
            f"dependency is too old. Minimum supported is {adblock_info.min_version}."
        )
    elif not adblock_info.is_installed():
        message.warning(
            "The 'adblock' dependency is not installed, ads are not blocked."
        )


_RESOURCE_TYPE_STRINGS = {
    ResourceType.main_frame: "main_frame",
    ResourceType.sub_frame: "sub_frame",
    ResourceType.stylesheet: "stylesheet",
    ResourceType.script: "script",
    ResourceType.image: "image",
    ResourceType.font_resource: "font",
    ResourceType.sub_resource: "sub_frame",
    ResourceType.object: "object",
    ResourceType.media: "media",
    ResourceType.worker: "other",
    ResourceType.shared_worker: "other",
    ResourceType.prefetch: "other",
    ResourceType.favicon: "image",
    ResourceType.xhr: "xhr",
    ResourceType.ping: "ping",
    ResourceType.service_worker: "other",
    ResourceType.csp_report: "csp_report",
    ResourceType.plugin_resource: "other",
    ResourceType.preload_main_frame: "other",
    ResourceType.preload_sub_frame: "other",
    ResourceType.websocket: "websocket",
    ResourceType.json: "other",
    ResourceType.unknown: "other",
    None: "",
}


def _resource_type_to_string(resource_type: ResourceType | None) -> str:
    return _RESOURCE_TYPE_STRINGS.get(resource_type, "other")


@dataclasses.dataclass
class CosmeticResources:

    """The cosmetic rules applying to a page.

    Attributes:
        hide_selectors: CSS selectors of elements to hide.
        style_selectors: CSS declarations to apply, by selector.
        exceptions: Selectors which must not be hidden on the page.
        generic: Whether rules which aren't specific to the page apply too.
    """

    hide_selectors: list[str]
    style_selectors: dict[str, list[str]]
    exceptions: set[str]
    generic: bool


class DeserializationError(Exception):

    """Custom exception for adblock.DeserializationErrors.

    See _map_exception below for details.
    """


@contextlib.contextmanager
def _map_exceptions() -> Iterator[None]:
    """Handle exception API differences in adblock 0.5.0.

    adblock < 0.5.0 will raise a ValueError with a string describing the
    exception class for all exceptions. With adblock 0.5.0+, it raises proper
    exception classes.

    This context manager unifies the two (only for DeserializationError so far).
    """
    adblock_deserialization_error = getattr(
        adblock, "DeserializationError", ValueError)

    try:
        yield
    except adblock_deserialization_error as e:
        if isinstance(e, ValueError) and str(e) != "DeserializationError":
            # All Rust exceptions get turned into a ValueError by
            # python-adblock
            raise
        raise DeserializationError(str(e))


class BraveAdBlocker:

    """Manage blocked hosts based on Brave's adblocker.

    Attributes:
        _has_basedir: Whether a custom --basedir is set.
        _cache_path: The path of the adblock engine cache file
        _engine: Brave ad-blocking engine.
        _update_running: Whether the block lists are being downloaded.
        _auto_update_timers: The timers triggering automatic updates.
    """

    def __init__(self, *, data_dir: pathlib.Path, has_basedir: bool = False) -> None:
        self._has_basedir = has_basedir
        self._cache_path = data_dir / "adblock-cache.dat"
        self._update_running = False
        self._auto_update_timers: list[usertypes.Timer] = []
        try:
            self._engine = adblock.Engine(adblock.FilterSet())
        except AttributeError:
            # this should never happen - let's get some infos if it does
            logger.debug(f"adblock module: {adblock}")
            dist = version.distribution()
            if (dist is not None and
                    dist.parsed == version.Distribution.arch and
                    hasattr(adblock, "__file__")):
                proc = subprocess.run(
                    ['pacman', '-Qo', adblock.__file__],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                logger.debug(proc.stdout)
                logger.debug(proc.stderr)
            raise

    def _is_blocked(
        self,
        request_url: QUrl,
        first_party_url: QUrl | None = None,
        resource_type: interceptor.ResourceType | None = None,
    ) -> bool:
        """Check whether the given request is blocked."""
        if (
            first_party_url is None
            or not first_party_url.isValid()
            or first_party_url.scheme() == "file"
        ):
            # FIXME: It seems that when `first_party_url` is None, every URL
            # I try is blocked. This may have been a result of me incorrectly
            # using the upstream library, or an upstream bug. For now we don't
            # block any request with `first_party_url=None`.
            return False

        qtutils.ensure_valid(request_url)

        if not config.get("content.blocking.enabled", url=first_party_url):
            # Do nothing if adblocking is disabled for this site.
            return False

        result = self._engine.check_network_urls(
            request_url.toString(),
            first_party_url.toString(),
            _resource_type_to_string(resource_type),
        )

        if not result.matched:
            return False
        elif result.exception is not None and not result.important:
            # Exception is not `None` when the blocker matched on an exception
            # rule. Effectively this means that there was a match, but the
            # request should not be blocked.
            #
            # An `important` match means that exceptions should not apply and
            # no further checking is necessary--the request should be blocked.
            logger.debug(
                "Excepting %s from being blocked by %s because of %s",
                request_url.toDisplayString(),
                result.filter,
                result.exception,
            )
            return False
        elif blockutils.is_whitelisted_url(request_url):
            logger.debug(
                "Request to %s is whitelisted, thus not blocked",
                request_url.toDisplayString(),
            )
            return False
        return True

    def cosmetic_resources(self, url: QUrl) -> CosmeticResources | None:
        """Get the cosmetic rules for the page with the given URL.

        Return:
            None if elements shouldn't be hidden on the page at all.
        """
        if not url.isValid() or url.scheme() not in ["http", "https"]:
            return None
        if not (
            config.get("content.blocking.enabled", url=url)
            and config.get("content.blocking.adblock.hide_elements", url=url)
        ):
            return None

        resources = self._engine.url_cosmetic_resources(url.toString())
        return CosmeticResources(
            hide_selectors=sorted(resources.hide_selectors),
            style_selectors={
                selector: list(declarations)
                for selector, declarations in resources.style_selectors.items()
            },
            exceptions=set(resources.exceptions),
            generic=not resources.generichide,
        )

    def generic_hide_selectors(
        self, *, classes: list[str], ids: list[str], exceptions: set[str]
    ) -> list[str]:
        """Get the selectors to hide for the given classes and IDs.

        This covers the generic rules for a single class or ID, which aren't
        part of what cosmetic_resources() returns.
        """
        return self._engine.hidden_class_id_selectors(classes, ids, exceptions)

    def filter_request(self, info: interceptor.Request) -> None:
        """Block the given request if necessary."""
        if self._is_blocked(info.request_url, info.first_party_url, info.resource_type):
            logger.debug(
                "Request to %s blocked by ad blocker.",
                info.request_url.toDisplayString(),
            )
            info.block()

    def read_cache(self) -> None:
        """Initialize the adblocking engine from cache file."""
        try:
            cache_exists = self._cache_path.is_file()
        except OSError:
            logger.error("Failed to read adblock cache", exc_info=True)
            return

        if cache_exists:
            logger.debug("Loading cached adblock data: %s", self._cache_path)
            try:
                with _map_exceptions():
                    self._engine.deserialize_from_file(str(self._cache_path))
            except DeserializationError:
                message.error("Reading adblock filter data failed (corrupted data?). "
                              "Please run :adblock-update.")
            except OSError as e:
                message.error(f"Reading adblock filter data failed: {e}")
        elif (
            config.val.content.blocking.adblock.lists
            and not self._has_basedir
            and config.val.content.blocking.enabled
            and not config.val.content.blocking.adblock.update_interval
        ):
            message.info("Run :adblock-update to get adblock lists.")

    def _lists_outdated(self) -> bool:
        """Check whether the block lists are due for an automatic update."""
        interval = config.val.content.blocking.adblock.update_interval
        if (
            not interval
            or self._has_basedir
            or not config.val.content.blocking.adblock.lists
            or not config.val.content.blocking.enabled
        ):
            return False

        try:
            age = time.time() - self._cache_path.stat().st_mtime
        except FileNotFoundError:
            return True
        except OSError:
            logger.exception("Failed to get the age of the adblock cache")
            return False
        return age >= interval * 24 * 60 * 60

    def auto_update(self) -> None:
        """Update the block lists in the background if they are outdated."""
        if self._update_running or not self._lists_outdated():
            return
        self.adblock_update(quiet=True)

    def start_auto_update(self) -> None:
        """Check for outdated block lists soon, and then regularly."""
        startup_timer = usertypes.Timer(name='adblock-update-startup')
        startup_timer.setSingleShot(True)
        startup_timer.setInterval(_AUTO_UPDATE_STARTUP_DELAY)
        regular_timer = usertypes.Timer(name='adblock-update-regular')
        regular_timer.setInterval(_AUTO_UPDATE_CHECK_INTERVAL)
        self._auto_update_timers = [startup_timer, regular_timer]
        for timer in self._auto_update_timers:
            timer.timeout.connect(self.auto_update)
            timer.start()

    def adblock_update(self, *, quiet: bool = False) -> blockutils.BlocklistDownloads:
        """Update the adblock block lists.

        Args:
            quiet: Only log the outcome instead of showing messages, used for
                   automatic updates.
        """
        logger.info("Downloading adblock filter lists...")
        self._update_running = True

        filter_set = adblock.FilterSet()
        dl = blockutils.BlocklistDownloads(config.val.content.blocking.adblock.lists)
        dl.single_download_finished.connect(
            functools.partial(self._on_download_finished, filter_set=filter_set)
        )
        dl.all_downloads_finished.connect(
            functools.partial(self._on_lists_downloaded, filter_set=filter_set,
                              downloads=dl, quiet=quiet)
        )
        dl.initiate()
        return dl

    def _on_lists_downloaded(
        self,
        done_count: int,
        filter_set: "adblock.FilterSet",
        downloads: blockutils.BlocklistDownloads,
        quiet: bool,
    ) -> None:
        """Install block lists after files have been downloaded.

        If any of them could not be read, we keep what we have: Otherwise, a
        failed update (e.g. without a network connection) would leave us with
        less blocked than before, or nothing at all.
        """
        self._update_running = False

        if downloads.failed_count:
            text = (f"braveadblock: {downloads.failed_count} block list(s) could "
                    "not be read, keeping the existing filters.")
            if quiet:
                logger.warning(text)
            else:
                message.error(text)
            return

        self._engine = adblock.Engine(filter_set)
        self._engine.serialize_to_file(str(self._cache_path))
        text = f"braveadblock: Filters successfully read from {done_count} sources."
        if quiet:
            logger.info(text)
        else:
            message.info(text)

    def update_files(self) -> None:
        """Update files when the config changed."""
        if not config.val.content.blocking.adblock.lists:
            try:
                self._cache_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.exception("Failed to remove adblock cache file: %s", e)

    def _on_download_finished(
        self, fileobj: IO[bytes], filter_set: "adblock.FilterSet"
    ) -> None:
        """When a blocklist download finishes, add it to the given filter set.

        Arguments:
            fileobj: The finished download's contents.
        """
        fileobj.seek(0)
        try:
            with io.TextIOWrapper(fileobj, encoding="utf-8") as text_io:
                filter_set.add_filter_list(text_io.read())
        except UnicodeDecodeError:
            message.info("braveadblock: Block list is not valid utf-8")


@hook.config_changed("content.blocking.adblock.lists")
def on_lists_changed() -> None:
    """Remove cached blocker from disk when blocklist changes."""
    if ad_blocker is not None:
        ad_blocker.update_files()


@hook.init()
def init(context: apitypes.InitContext) -> None:
    """Initialize the Brave ad blocker."""
    global ad_blocker

    adblock_info = version.MODULE_INFO["adblock"]
    if not adblock_info.is_usable():
        # We want 'adblock' to be an optional dependency. If the module is
        # not installed or is outdated, we simply keep the `ad_blocker` global at
        # `None`.
        _possibly_show_missing_dependency_warning()
        return

    ad_blocker = BraveAdBlocker(
        data_dir=context.data_dir, has_basedir=context.args.basedir is not None
    )
    ad_blocker.read_cache()
    ad_blocker.start_auto_update()
    interceptor.register(ad_blocker.filter_request)
