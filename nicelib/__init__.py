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


def load_lib(name, pkg, builder=None, kwargs={}):
    """Load a low-level lib module, building it if required

    If `name` is `foo`, tries to import a module named `_foolib`. If the module can't be located,
    `load_lib` tries to build it.

    `builder` is the name of the module whose `build()` function is used to generate `_foolib.py`.
    By default, it is assumed to be `_build_foo` (where 'foo' is the value of `name`).

    `kwargs`, if given, is a dict of keyword args that is passed to `build()`.
    """
    lib_name = '._{}lib'.format(name)
    try:
        lib_module = import_module(lib_name, pkg)
    except ImportError:
        if builder is None:
            builder = '._build_{}'.format(name)
        build_module = import_module(builder, pkg)
        build_module.build(**kwargs)
        lib_module = import_module(lib_name, pkg)

    return LibInfo(lib_module)


from .nicelib import NiceLib, NiceObjectDef
from .build import build_lib
from .process import generate_bindings

__all__ = ['NiceLib', 'NiceObjectDef', 'build_lib', 'load_lib', 'generate_bindings']
