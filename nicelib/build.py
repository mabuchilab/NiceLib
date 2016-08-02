# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from __future__ import print_function
from past.builtins import basestring

import sys
import os
import os.path
from fnmatch import fnmatch
import cffi
from .process import process_headers

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


def build_lib(header_info, lib_name, module_name, filedir, ignored_headers=(),
              ignore_system_headers=False, preamble=None, token_hooks=(), ast_hooks=(),
              hook_groups=(), debug_file=None):
    """Build a low-level Python wrapper of a C lib

    Parameters
    ----------
    header_info : str or dict
        Path to header file. Paths can use ``os.environ``, as described below. Info is provided in
        the form of a dict which must contain a 'header' key whose value is either a str containing
        a single header name, or a tuple of such strings.

        There are also some other optional entries:

        The ``'path'`` value must be a str or tuple of strs that are directories which will be
        searched for the given header(s). Any headers that are specified with a leading slash are
        considered absolute and are not affected by this path.

        The ``'predef'`` value is a str which is the name or path of a header file which will be
        used to populate the predefined preprocessor macros that are ordinarily provided by the
        compiler on a per-system basis. If provided, this overrides the default header that NiceLib
        uses for your system.
    lib_name : str or dict
        Name of compiled library file, e.g. ``'mylib.dll'``
    module_name : str
        Name of module to create. Must be in the format ``'_*lib'``, e.g. ``'_mylib'``
    filedir : str
        Path indicating the directory where the generated module will be saved. If `filedir` points
        to an existing file, that file's directory is used. Usually you would pass the ``__file__``
        attribute from your build module.
    ignored_headers : sequence of strs
        Names of headers to ignore; `#include`\s containing these will be skipped.
    ignore_system_headers : bool
        If True, skip inclusion of headers specified with angle brackets, e.g. `#include
        <stdarg.h>` Header files specified with double quotes are processed as ususal. Default is
        False.
    token_hooks : sequence of functions
        Token hook functions. See `process_headers()` for more info.
    ast_hooks : sequence of functions
        AST hook functions. See `process_headers()` for more info.
    hook_groups : str or sequence of strs
        Hook groups. See `process_headers()` for more info.

    Notes
    -----
    ``header_info`` and ``lib_name`` can each be a dict that maps from a platform to the
    corresponding path or name, allowing cross-platform support. The keys are matched against
    ``sys.platform`` and can use globbing, i.e. ``'linux*'`` will match anything starting with
    ``'linux'``.

    The path or paths provided by ``header_info`` may use items in ``os.environ``. For example,
    ``'{PROGRAMFILES}\\\\header.h'`` will be formatted with ``os.environ['PROGRAMFILES']``.
    """
    print("Module {} does not yet exist, building it now. "
          "This may take a minute...".format(module_name))

    print("Searching for headers...")
    header_paths, predef_path = handle_header_path(header_info)
    print("Found {}".format(header_paths))

    lib_name = handle_lib_name(lib_name)

    if not (module_name.startswith('_') and module_name.endswith('lib')):
        raise TypeError("Module name must use the format '_*lib'")

    if os.path.isfile(filedir):
        filedir, _ = os.path.split(filedir)
    filedir = os.path.realpath(filedir)

    def update_cb(cur_line, tot_lines):
        sys.stdout.write("Parsing line {}/{}\r".format(cur_line, tot_lines))
        sys.stdout.flush()

    #header_name = os.path.basename(header_path)
    #print("Parsing and cleaning header {}".format(header_name))
    clean_header_str, macro_code = process_headers(header_paths, predef_path, update_cb=update_cb,
                                                   ignored_headers=ignored_headers,
                                                   ignore_system_headers=ignore_system_headers,
                                                   preamble=preamble, token_hooks=token_hooks,
                                                   ast_hooks=ast_hooks, hook_groups=hook_groups,
                                                   debug_file=debug_file)

    print("Compiling cffi module...")
    ffi = cffi.FFI()
    ffi.cdef(clean_header_str)
    ffi.set_source('.' + module_name, None)
    ffi.compile(tmpdir=filedir)

    print("Writing macros...")

    module_path = os.path.join(filedir, module_name + '.py')
    with open(module_path, 'a') as f:
        f.write("lib = ffi.dlopen('{}')\n".format(lib_name))
        f.write("class Defs(object): pass\ndefs = Defs()\n")
        f.write(macro_code)

    print("Done building {}".format(module_name))
