# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from past.builtins import basestring

import sys
import os
import os.path
from fnmatch import fnmatch

is_64bit = sys.maxsize > 2**32


def select_platform_value(platform_dict):
    for platform_pattern, value in platform_dict.items():
        bitwidth = None
        if ':' in platform_pattern:
            platform_pattern, bitwidth = platform_pattern.split(':')
            if bitwidth not in ('32', '64'):
                raise ValueError("Only support 32 or 64 bits, got '{}'".format(bitwidth))
            pattern_is_64bit = bitwidth == '64'

        if bitwidth is None or (pattern_is_64bit == is_64bit):
            if fnmatch(sys.platform, platform_pattern):
                return value
    raise ValueError("No matching platform pattern found")


def to_tuple(value):
    """Convert value to a tuple, or if it is a string, wrap it in a tuple"""
    return (value,) if isinstance(value, basestring) else tuple(value)


def handle_header_path(path):
    if isinstance(path, basestring):
        if os.path.exists(path):
            return path
        else:
            raise ValueError("Cannot find library header")

    header_dict = select_platform_value(path)
    if 'header' not in header_dict:
        raise KeyError("Header dict must contain key 'header'")

    header_names = header_dict['header']
    header_names = (header_names,) if isinstance(header_names, basestring) else header_names

    include_dirs = header_dict.get('path', ())
    include_dirs = (include_dirs,) if isinstance(include_dirs, basestring) else include_dirs

    headers = [find_header(h, include_dirs) for h in header_names]

    if 'predef' in header_dict:
        predef_header = find_header(header_dict['predef'], include_dirs)
    else:
        predef_header = None

    return headers, predef_header


def find_header(header_name, include_dirs):
    try:
        header_name = header_name.format(**os.environ)
    except KeyError:
        pass

    if os.path.isabs(header_name):
        if os.path.exists(header_name):
            return header_name
    else:
        for include_dir in include_dirs:
            try:
                include_dir = include_dir.format(**os.environ)
            except KeyError:
                pass

            if not os.path.isabs(include_dir):
                raise Exception("Header include paths must be absolute")

            path = os.path.join(include_dir, header_name)
            if os.path.exists(path):
                return path

    raise Exception("Cannot find header '{}'".format(header_name))


def handle_lib_name(lib_name):
    if isinstance(lib_name, basestring):
        return lib_name
    return select_platform_value(lib_name)
