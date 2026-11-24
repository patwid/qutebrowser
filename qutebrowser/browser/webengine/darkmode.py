# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Get darkmode arguments to pass to Qt.

Dark mode is turned on/off at runtime via QWebEngineSettings (see
webenginesettings.py). Everything else is configured via Chromium commandline
switches, which is what this module takes care of:

- All dark mode settings go to the --dark-mode-settings switch, see Chromium's
  dark_mode_settings.h.
- "prefers color scheme" is passed via --blink-settings, and needs to be 0 for dark
  and 1 for light.
"""

import dataclasses
import collections
from typing import (Any, TypeAlias)
from collections.abc import Mapping, Sequence

from qutebrowser.config import config
from qutebrowser.utils import usertypes


_BLINK_SETTINGS = 'blink-settings'
_DARK_MODE_SETTINGS = 'dark-mode-settings'


# Mapping from a colors.webpage.darkmode.algorithm setting value to
# Chromium's DarkModeInversionAlgorithm enum values.
# Based on dark_mode_settings.h
_ALGORITHMS = {
    # 0: kSimpleInvertForTesting (not exposed)
    'brightness-rgb': 1,  # kInvertBrightness
    'lightness-hsl': 2,  # kInvertLightness
    'lightness-cielab': 3,  # kInvertLightnessLAB
}

# Mapping from a colors.webpage.darkmode.policy.images setting value to
# Chromium's DarkModeImagePolicy enum values.
# Values line up with dark_mode_settings.h.
_IMAGE_POLICIES = {
    'always': 0,  # kFilterAll
    'never': 1,  # kFilterNone
    'smart': 2,  # kFilterSmart
    'smart-simple': 2,  # kFilterSmart
}

# Using the colors.webpage.darkmode.policy.images setting, shared with _IMAGE_POLICIES
_IMAGE_CLASSIFIERS = {
    'always': None,
    'never': None,
    'smart': 0,  # kNumColorsWithMlFallback
    'smart-simple': 1,  # kTransparencyAndNumColors
}


@dataclasses.dataclass
class _Setting:

    """A single dark mode setting."""

    option: str
    chromium_key: str
    mapping: Mapping[Any, str | int | None] | None = None

    def _value_str(self, value: Any) -> str:
        if self.mapping is None:
            return str(value)
        return str(self.mapping[value])

    def chromium_tuple(self, value: Any) -> tuple[str, str] | None:
        """Get the Chromium key and value, or None if no value should be set."""
        if self.mapping is not None and self.mapping[value] is None:
            return None
        return self.chromium_key, self._value_str(value)


_SETTINGS: Sequence[_Setting] = [
    _Setting('algorithm', 'InversionAlgorithm', _ALGORITHMS),

    _Setting('policy.images', 'ImagePolicy', _IMAGE_POLICIES),
    _Setting('contrast', 'ContrastPercent'),

    _Setting('threshold.foreground', 'ForegroundBrightnessThreshold'),
    _Setting('threshold.background', 'BackgroundBrightnessThreshold'),

    _Setting('policy.images', 'ImageClassifierPolicy', _IMAGE_CLASSIFIERS),
]

# Our defaults for policy.images are different from Chromium's, so we mark it as
# mandatory setting.
_MANDATORY = {'policy.images'}


_SettingValType: TypeAlias = str | usertypes.Unset
_PREFERRED_COLOR_SCHEME_DEFINITION: Mapping[_SettingValType, str] = {
    "dark": "0",
    "light": "1",
}


def settings(
        *,
        special_flags: Sequence[str],
) -> Mapping[str, Sequence[tuple[str, str]]]:
    """Get necessary Chromium settings to configure dark mode for QtWebEngine.

    Args:
       Existing '--blink-settings=...' flags, if any.

    Returns:
        A dict which maps Chromium switch names (blink-settings or dark-mode-settings)
        to a sequence of tuples, each tuple being a key/value pair to pass to that
        setting.
    """
    result: Mapping[str, list[tuple[str, str]]] = collections.defaultdict(list)

    blink_settings_flag = f'--{_BLINK_SETTINGS}='
    for flag in special_flags:
        if flag.startswith(blink_settings_flag):
            for pair in flag.removeprefix(blink_settings_flag).split(','):
                key, val = pair.split('=', maxsplit=1)
                result[_BLINK_SETTINGS].append((key, val))

    preferred_color_scheme_key = config.instance.get(
        "colors.webpage.preferred_color_scheme", fallback=False)
    if preferred_color_scheme_key in _PREFERRED_COLOR_SCHEME_DEFINITION:
        value = _PREFERRED_COLOR_SCHEME_DEFINITION[preferred_color_scheme_key]
        result[_BLINK_SETTINGS].append(("preferredColorScheme", value))

    if not config.val.colors.webpage.darkmode.enabled:
        return result

    for setting in _SETTINGS:
        # To avoid blowing up the commandline length, we only pass modified
        # settings to Chromium, as our defaults line up with Chromium's.
        # However, we always pass mandatory settings, where our defaults differ.
        value = config.instance.get(
            'colors.webpage.darkmode.' + setting.option,
            fallback=setting.option in _MANDATORY)
        if isinstance(value, usertypes.Unset):
            continue

        chromium_tuple = setting.chromium_tuple(value)
        if chromium_tuple is not None:
            result[_DARK_MODE_SETTINGS].append(chromium_tuple)

    return result
