# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from importlib import import_module
from .__about__ import __version__


class LibInfo(object):
    def __init__(self, lib_module=None, prefix=None):
        if lib_module:
            self._ffi = lib_module.ffi
            self._ffilib = lib_module.lib
            self._defs = lib_module.defs
            self.__dict__.update(self._defs)
            self._build_version = lib_module.build_version
        else:
            self._ffi = None
            self._ffilib = None
            self._defs = None

    def __getattr__(self, name):
        return getattr(self._ffilib, name)


def load_lib(name, pkg):
    """Load a low-level lib module, building it if required

    If `name` is `foo`, tries to import a module named `_foolib`. If that fails, tries to import
    `_build_foo` and call its `build()` function, which is supposed to generate `_foolib.py`.
    """
    try:
        lib_module = import_module('._{}lib'.format(name), pkg)
    except ImportError:
        build_module = import_module('._build_{}'.format(name), pkg)
        build_module.build()
        lib_module = import_module('._{}lib'.format(name), pkg)

    return LibInfo(lib_module)


from .nicelib import NiceLib, NiceObjectDef
from .build import build_lib
from .process import generate_bindings

__all__ = ['NiceLib', 'NiceObjectDef', 'build_lib', 'load_lib', 'generate_bindings']
