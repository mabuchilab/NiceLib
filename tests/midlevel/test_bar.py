import sys
from nicelib import NiceLib, load_lib, Sig, NiceObject


class NiceBar(NiceLib):
    """Foo library"""
    _info = load_lib('bar', pkg=None, dir=__file__)
    

def test_bar():
    ffi = NiceBar._ffi
    test = ffi.new('Test*')
    assert ffi.sizeof(test) == 2*ffi.sizeof('char')+ffi.sizeof('int')