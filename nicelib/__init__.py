# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from __future__ import division, absolute_import, with_statement, print_function, unicode_literals


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
from .nicelib import NiceLib, NiceObject
from .build import build_lib

__all__ = ['NiceLib', 'NiceObject', 'build_lib']
