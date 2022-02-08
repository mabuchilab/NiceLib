import sys
from nicelib import NiceLib, load_lib


class NiceBar(NiceLib):
    """Bar packed"""
    _info = load_lib('bar', pkg=None, dir=__file__)

    
class NiceBar2(NiceLib):
    """Bar2 not packed"""
    _info = load_lib('bar2', pkg=None, dir=__file__)


def test_packed():
    ffi = NiceBar._ffi
    test = ffi.new('Test*')    
    assert ffi.sizeof(test[0]) == 2*ffi.sizeof('char')+ffi.sizeof('int')

def test_unpacked():
    ffi = NiceBar2._ffi
    test = ffi.new('Test*')    
    assert ffi.sizeof(test[0]) > 2*ffi.sizeof('char')+ffi.sizeof('int')