# -*- coding: utf-8 -*-
# Copyright 2016-2018 Nate Bogdanowicz
from __future__ import division, absolute_import, with_statement, print_function, unicode_literals

import sys
import os.path
from importlib import import_module

from .__about__ import __version__


class LibInfo(object):
    def __init__(self, lib_module=None, prefix=None):
        if lib_module:
            self._ffi = lib_module.ffi
            self._ffilib = lib_module.lib
            self._defs = lib_module.defs
            self.__dict__.update(self._defs)
            self._argnames = getattr(lib_module, 'argnames', {})
            self._build_version = lib_module.build_version
        else:
            self._ffi = None
            self._ffilib = None
            self._defs = None
            self._argnames = {}

    def __getattr__(self, name):
        return getattr(self._ffilib, name)


def load_lib(name, pkg=None, dir=None, builder=None, kwargs={}):
    """Load a low-level lib module, building it first if required.

    If ``name`` is ``'foo'``, tries to import a module named ``_foolib``. If the module can't be located,
    `load_lib` tries to build it.

    Parameters
    ----------
    name : str
        The name of the library. A name of ``'foo'`` would try to import the module ``_foolib``.
    pkg : str
        The package within which to look for the module. If None, looks for a top-level module.
    dir : str
        A directory within which to search for the module, before checking the system path. Useful
        when working with local modules not within a package.
    builder : str, optional
        The name of the module whose ``build()`` function is used to generate ``_foolib.py`` By
        default, it is assumed to be ``_build_foo`` (where 'foo' is the value of ``name``).
    kwargs : dict, optional
        Keyword args to be passed to ``build()``.

    Returns
    -------
    lib : LibInfo
    """
    prefix = '.' if pkg else ''
    lib_name = prefix + '_{}lib'.format(name)
    if dir:
        sys.path.insert(0, os.path.dirname(dir))

    try:
        lib_module = import_module(lib_name, pkg)
    except ImportError:
        if builder is None:
            builder = prefix + '_build_{}'.format(name)
        build_module = import_module(builder, pkg)
        build_module.build(**kwargs)
        lib_module = import_module(lib_name, pkg)

    return LibInfo(lib_module)


from .nicelib import (NiceLib, NiceObjectDef, NiceObject, RetHandler, ret_return, ret_ignore,
                      Sig, sig_pattern)
from .build import build_lib
from .process import generate_bindings

__all__ = ['NiceLib', 'NiceObjectDef', 'build_lib', 'load_lib', 'generate_bindings', 'NiceObject',
           'RetHandler', 'ret_return', 'ret_ignore', 'Sig', 'sig_pattern', '__version__']
