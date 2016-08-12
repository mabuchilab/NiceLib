# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from importlib import import_module


class TestMode(object):
    arg_modes = ('run', 'record', 'replay', 'run-or-replay', 'record-if-missing')
    modes = ('run', 'record', 'replay')

    def __init__(self, mode):
        self.arg_mode = None
        self.mode = None  # 'None' means not testing (different from 'run')

    def set_arg_mode(self, mode):
        if mode not in self.arg_modes:
            raise ValueError("Mode must be one of {}".format(self.arg_modes))
        self.arg_mode = mode

    def set_mode(self, mode):
        if mode not in self.modes:
            raise ValueError("Mode must be one of {}".format(self.modes))
        self.mode = mode

_test_mode = TestMode('run')


def set_test_mode(mode):
    _test_mode.set_arg_mode(mode)


def test_mode_is(*modes):
    return _test_mode.mode in modes


def get_test_mode():
    return _test_mode.mode


def arg_mode_is(*modes):
    return _test_mode.arg_mode in modes


class LibInfo(object):
    def __init__(self, lib_module=None, prefix=None):
        if lib_module:
            self._ffi = lib_module.ffi
            self._ffilib = lib_module.lib
            self._defs = lib_module.defs
            self.__dict__.update(self._defs)
        else:
            self._ffi = None
            self._ffilib = None
            self._defs = None

    def __getattr__(self, name):
        return getattr(self._ffilib, name)


def _load_or_build_lib(name, pkg):
    try:
        lib_module = import_module('._{}lib'.format(name), pkg)
    except ImportError:
        build_module = import_module('._build_{}'.format(name), pkg)
        build_module.build()
        lib_module = import_module('._{}lib'.format(name), pkg)

    return LibInfo(lib_module)


def load_lib(name, pkg):
    lib_module = None
    if arg_mode_is(None):
        lib_module = _load_or_build_lib(name, pkg)

    elif arg_mode_is('run', 'record', 'record-if-missing'):
        lib_module = _load_or_build_lib(name, pkg)
        if arg_mode_is('run'):
            _test_mode.set_mode('run')
        else:
            _test_mode.set_mode('record')

    elif arg_mode_is('replay'):
        lib_module = LibInfo()
        _test_mode.set_mode('replay')

    elif arg_mode_is('run-or-replay'):
        if test_mode_is('none', 'run'):  # All lib imports so far have been successful
            try:
                lib_module = _load_or_build_lib(name, pkg)
                _test_mode.set_mode('run')
            except ImportError:
                _test_mode.set_mode('replay')

        if test_mode_is('replay'):  # At least one lib import has failed
            lib_module = LibInfo()

    if not lib_module:
        raise ValueError("Invalid mode '{}'".format(get_test_mode()))

    return lib_module


from .nicelib import NiceLib, NiceObjectDef
from .build import build_lib
from .process import generate_bindings

__all__ = ['NiceLib', 'NiceObjectDef', 'build_lib', 'load_lib', 'generate_bindings']
