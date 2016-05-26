# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from __future__ import print_function
from past.builtins import basestring

import sys
import os
import os.path
from fnmatch import fnmatch
import cffi
from .process import process_header


def handle_header_path(path):
    if isinstance(path, basestring):
        if os.path.exists(path):
            return path
        else:
            raise Exception("Cannot find library header")

    header_path_lookup = path
    for platform_pattern, paths in header_path_lookup.items():
        if fnmatch(sys.platform, platform_pattern):
            for path in paths:
                try:
                    path = path.format(**os.environ)
                    if os.path.exists(path):
                        return path
                except KeyError:
                    pass

    raise Exception("Cannot find library header")


def handle_lib_name(lib_name):
    if isinstance(lib_name, basestring):
        return lib_name

    lib_name_lookup = lib_name
    for platform_pattern, name in lib_name_lookup.items():
        if fnmatch(sys.platform, platform_pattern):
            return name

    raise Exception("No library name given for your platform")


def build_lib(header_path, lib_name, module_name):
    """Build a low-level Python wrapper of a C lib

    Parameters
    ----------
    header_path : str or dict
        Path to header file. Paths can use ``os.environ``, as described below
    lib_name : str or dict
        Name of compiled library file, e.g. 'mylib.dll'
    module_name : str
        Name of module to create. Must be in the format '_*lib', e.g. '_mylib'

    Notes
    -----
    ``header_path`` and ``lib_name`` can each be a dict that maps from a platform to the
    corresponding path or name, allowing cross-platform support. The keys are matched against
    ``sys.platform`` and can use globbing, i.e. 'linux*' will match anything starting with 'linux'.

    The path or paths provided by ``header_path`` may use items in ``os.environ``. For example,
    "{PROGRAMFILES}\\\\header.h" will be formatted with ``os.environ['PROGRAMFILES']``.
    """
    print("Module {} does not yet exist, building it now. "
          "This may take a minute...".format(module_name))

    print("Searching for headers...")
    header_path = handle_header_path(header_path)
    print("Found {}".format(header_path))

    lib_name = handle_lib_name(lib_name)

    if not (module_name.startswith('_') and module_name.endswith('lib')):
        raise TypeError("Module name must use the format '_*lib'")

    def update_cb(cur_line, tot_lines):
        sys.stdout.write("Parsing line {}/{}\r".format(cur_line, tot_lines))
        sys.stdout.flush()

    header_name = os.path.basename(header_path)
    print("Parsing and cleaning header {}".format(header_name))
    clean_header_str, macro_code = process_header(header_path, minify=True, update_cb=update_cb)

    print("Compiling cffi module...")
    ffi = cffi.FFI()
    ffi.cdef(clean_header_str)
    ffi.set_source('.' + module_name, None)
    ffi.compile()

    print("Writing macros...")

    with open(module_name + '.py', 'a') as f:
        f.write("lib = ffi.dlopen('{}')\n".format(lib_name))
        f.write("class Defs(object): pass\ndefs = Defs()\n")
        f.write(macro_code)

    print("Done building {}".format(module_name))
