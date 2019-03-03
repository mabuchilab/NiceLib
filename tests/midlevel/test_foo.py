import sys
from nicelib import NiceLib, load_lib, Sig, NiceObject, ret_ignore, ret_return


class NiceFoo(NiceLib):
    """Foo library"""
    _info = load_lib('foo', pkg=None, dir=__file__)
    _ret = ret_return

    add = Sig('in', 'in')
    subtract = Sig('in', 'in')
    create_item = Sig()

    class Item(NiceObject):
        _init_ = 'create_item'
        _prefix_ = 'item_'

        get_id = Sig('in')
        get_value = Sig('in')
        set_value = Sig('in', 'in')
        static_value = Sig(use_handle=False)


def test_add():
    assert NiceFoo.add(2, 2) == 4


def test_static_method():
    item = NiceFoo.Item()
    assert item.static_value() == 5


def test_kwargs():
    if sys.version_info < (3,3):
        return
    assert NiceFoo.subtract(7, b=5) == 2
    assert NiceFoo.subtract(a=7, b=5) == 2
    assert NiceFoo.subtract(b=5, a=7) == 2
