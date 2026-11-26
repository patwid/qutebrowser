# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configuration data for config.py.

Module attributes:

DATA: A dict of Option objects after init() has been called.
"""

from typing import Any, NoReturn, cast
from collections.abc import Mapping, MutableMapping
import functools
import dataclasses

from qutebrowser.config import configtypes
from qutebrowser.utils import utils, resources
from qutebrowser.misc import debugcachestats

DATA = cast(Mapping[str, 'Option'], None)


@dataclasses.dataclass(order=True)
class Option:

    """Description of an Option in the config.

    Note that this is just an option which exists, with no value associated.
    """

    name: str
    typ: configtypes.BaseType
    default: Any
    description: str
    supports_pattern: bool = False
    restart: bool = False
    no_autoconfig: bool = False


def _raise_invalid_node(name: str, what: str, node: Any) -> NoReturn:
    """Raise an exception for an invalid configdata YAML node.

    Args:
        name: The name of the setting being parsed.
        what: The name of the thing being parsed.
        node: The invalid node.
    """
    raise ValueError("Invalid node for {} while reading {}: {!r}".format(
        name, what, node))


def _parse_yaml_type(
        name: str,
        node: str | Mapping[str, Any],
) -> configtypes.BaseType:
    if isinstance(node, str):
        # e.g:
        #   > type: Bool
        # -> create the type object without any arguments
        type_name = node
        kwargs: MutableMapping[str, Any] = {}
    elif isinstance(node, dict):
        # e.g:
        #   > type:
        #   >   name: String
        #   >   none_ok: true
        # -> create the type object and pass arguments
        type_name = node.pop('name')
        kwargs = node
        valid_values = kwargs.get('valid_values', None)
        if valid_values is not None:
            kwargs['valid_values'] = configtypes.ValidValues(*valid_values)
    else:
        _raise_invalid_node(name, 'type', node)

    try:
        typ = getattr(configtypes, type_name)
    except AttributeError:
        raise AttributeError("Did not find type {} for {}".format(
            type_name, name))

    # Parse sub-types
    try:
        if typ is configtypes.Dict:
            kwargs['keytype'] = _parse_yaml_type(name, kwargs['keytype'])
            kwargs['valtype'] = _parse_yaml_type(name, kwargs['valtype'])
        elif typ is configtypes.List or typ is configtypes.ListOrValue:
            kwargs['valtype'] = _parse_yaml_type(name, kwargs['valtype'])
    except KeyError as e:
        _raise_invalid_node(name, str(e), node)

    try:
        return typ(**kwargs)
    except TypeError as e:
        raise TypeError("Error while creating {} with {}: {}".format(
            type_name, node, e))


def _read_yaml(
        yaml_data: str,
) -> Mapping[str, Option]:
    """Read config data from a YAML file.

    Args:
        yaml_data: The YAML string to parse.

    Return:
        A dict mapping option names to Option elements.
    """
    parsed = {}
    data = utils.yaml_load(yaml_data)

    keys = {'type', 'default', 'desc', 'restart',
            'supports_pattern', 'no_autoconfig'}

    for name, option in data.items():
        if not set(option.keys()).issubset(keys):
            raise ValueError("Invalid keys {} for {}".format(
                option.keys(), name))

        parsed[name] = Option(
            name=name,
            typ=_parse_yaml_type(name, option['type']),
            default=option['default'],
            description=option['desc'],
            restart=option.get('restart', False),
            supports_pattern=option.get('supports_pattern', False),
            no_autoconfig=option.get('no_autoconfig', False),
        )

    # Make sure no key shadows another.
    for key1 in parsed:
        for key2 in parsed:
            if key2.startswith(key1 + '.'):
                raise ValueError("Shadowing keys {} and {}".format(key1, key2))

    return parsed


@debugcachestats.register()
@functools.lru_cache(maxsize=256)
def is_valid_prefix(prefix: str) -> bool:
    """Check whether the given prefix is a valid prefix for some option."""
    return any(key.startswith(prefix + '.') for key in DATA)


def init() -> None:
    """Initialize configdata from the YAML file."""
    global DATA
    DATA = _read_yaml(resources.read_file('config/configdata.yml'))
