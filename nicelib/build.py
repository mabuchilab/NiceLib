# -*- coding: utf-8 -*-
# Copyright 2016-2018 Nate Bogdanowicz
from __future__ import print_function

import os
import os.path
import logging
import cffi
from .util import handle_header_path, handle_lib_name
from .process import process_headers, process_source
from .__about__ import __version__


log = logging.getLogger(__name__)


class LogBuffer(object):
    def write(self, msg):
        log.info(msg.rstrip('\n'))


def build_lib(header_info, lib_name, module_name, filedir, ignored_headers=(),
              ignore_system_headers=False, preamble=None, token_hooks=(), ast_hooks=(),
              hook_groups=(), debug_file=None, logbuf=None, load_dump_file=False,
              save_dump_file=False, pack=None, override=False):
    """Build a low-level Python wrapper of a C lib

    Parameters
    ----------
    header_info : str, dict, or None
        Path to header file. If None, uses only the header source given by ``preamble``.

        Paths can use ``os.environ``, as described below. Info is provided in the form of a dict
        which must contain a 'header' key whose value is either a str containing a single header
        name, or a tuple of such strings.

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
        Path indicating the directory where the generated module will be saved. If ``filedir``
        points to an existing file, that file's directory is used. Usually you would pass the
        ``__file__`` attribute from your build module.
    ignored_headers : sequence of strs
        Names of headers to ignore; ``#include``\s containing these will be skipped.
    ignore_system_headers : bool
        If True, skip inclusion of headers specified with angle brackets, e.g.
        ``#include <stdarg.h>`` Header files specified with double quotes are processed as ususal.
        Default is False.
    preamble : str
        C source to insert before the headers specified by ``header_info``. Useful for including
        typedefs that would otherwise be hard to reach due to an end user missing headers.
    token_hooks : sequence of functions
        Token hook functions. See `process_headers()` for more info.
    ast_hooks : sequence of functions
        AST hook functions. See `process_headers()` for more info.
    hook_groups : str or sequence of strs
        Hook groups. See `process_headers()` for more info.
    debug_file : str
        File to write a partially-processed header to just before it is parsed by ``pycparser``.
        Useful for debugging the preprocessor when ``pycparser``'s parser chokes on its output.
    logbuf : writeable buffer
        IO buffer to write() common log output to. By default this output will logged using the
        ``logging`` stdlib module, at the ``info`` log level. You can use ``sys.stdout`` to perform
        ordinary printing.
    load_dump_file : bool
        Save the list of tokens resulting from preprocessing to 'token_dump.pkl'. See save_dump_file
        for more info.
    save_dump_file : bool
        Ignore ``header_paths`` and load the already-preprocessed tokens from 'token_dump.pkl'. This
        can significantly speed up your turnaround time when debugging really large header sets
        when writing and debugging hooks.
    pack: int
        Forwared to ``FFI.cdef``. Controls the packing of structs if necessary. This has to be done
        manually since CFFI ignores ``#pragma pack`` and gcc directives. See the CFFI documentation
        for more information.
    override: bool
        Forwarded to ``FFI.cdef``. If True, allows repeated declarations; the final declaration will
        override any others. Otherwise, repeated declarations are treated as an error.

    Notes
    -----
    ``header_info`` and ``lib_name`` can each be a dict that maps from a platform to the
    corresponding path or name, allowing cross-platform support. The keys are matched against
    ``sys.platform`` and can use globbing, i.e. ``'linux*'`` will match anything starting with
    ``'linux'``.

    The path or paths provided by ``header_info`` may use items in ``os.environ``. For example,
    ``'{PROGRAMFILES}\\\\header.h'`` will be formatted with ``os.environ['PROGRAMFILES']``.
    """
    if logbuf is None:
        logbuf = LogBuffer()
        update_cb = None  # Don't do line-by-line update by default
    else:
        def update_cb(cur_line):
            logbuf.write("Parsing line {}\r".format(cur_line))
            try:
                logbuf.flush()
            except AttributeError:
                pass

    logbuf.write("Module {} does not yet exist, building it now. "
                 "This may take a minute...\n".format(module_name))

    if os.path.isfile(filedir):
        filedir, _ = os.path.split(filedir)
    filedir = os.path.realpath(filedir)

    if not (module_name.startswith('_') and module_name.endswith('lib')):
        raise TypeError("Module name must use the format '_*lib', got '{}'".format(module_name))

    lib_path = handle_lib_name(lib_name, filedir)

    if header_info:
        logbuf.write("Searching for headers...\n")
        header_paths, predef_path = handle_header_path(header_info, filedir)
        logbuf.write("Found {}\n".format(header_paths))

        logbuf.write("Parsing and cleaning headers...\n")
        retval = process_headers(header_paths, predef_path,
                                 update_cb=update_cb,
                                 ignored_headers=ignored_headers,
                                 ignore_system_headers=ignore_system_headers,
                                 preamble=preamble,
                                 token_hooks=token_hooks,
                                 ast_hooks=ast_hooks,
                                 hook_groups=hook_groups,
                                 debug_file=debug_file,
                                 load_dump_file=load_dump_file,
                                 save_dump_file=save_dump_file)
    else:
        if not preamble:
            raise ValueError('No header provided. Must give header_info and/or preamble')
        logbuf.write("Parsing and cleaning headers...\n")
        predef_path = None
        retval = process_source('', predef_path,
                                update_cb=update_cb,
                                ignored_headers=ignored_headers,
                                ignore_system_headers=ignore_system_headers,
                                preamble=preamble,
                                token_hooks=token_hooks,
                                ast_hooks=ast_hooks,
                                hook_groups=hook_groups,
                                debug_file=debug_file,
                                load_dump_file=load_dump_file,
                                save_dump_file=save_dump_file)

    clean_header_str, macro_code, argnames = retval

    logbuf.write("Compiling cffi module...\n")
    ffi = cffi.FFI()
    ffi.cdef(clean_header_str, pack=pack, override=override)
    ffi.set_source('.' + module_name, None)
    ffi.compile(tmpdir=filedir)

    logbuf.write("Writing macros...\n")

    module_path = os.path.join(filedir, module_name + '.py')
    with open(module_path, 'a') as f:
        f.write(MODULE_TEMPLATE.format(
            build_version=__version__,
            lib_dir=os.path.dirname(lib_path),
            lib_path=lib_path,
            macro_code=macro_code,
            argnames=argnames
        ))

    logbuf.write("Done building {}\n".format(module_name))


MODULE_TEMPLATE = """
import os
import os.path
build_version = {build_version!r}

# Change directory in case of dependent libs not on PATH
_old_curdir = os.path.abspath(os.curdir)
if {lib_dir!r}:
    os.chdir({lib_dir!r})
lib = ffi.dlopen({lib_path!r})
os.chdir(_old_curdir)

{macro_code}

argnames = {argnames!r}
"""
