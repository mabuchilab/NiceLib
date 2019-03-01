from nicelib import NiceLib, load_lib, Sig, NiceObject, ret_ignore, ret_return


class NiceFoo(NiceLib):
    """Foo library"""
    _info = load_lib('foo', pkg=None, dir=__file__)
    _ret = ret_return

    add = Sig('in', 'in')
    create_item = Sig()

    class Item(NiceObject):
        _init_ = 'create_item'
        _prefix_ = 'item_'

        get_id = Sig('in')
        get_value = Sig('in', ret=ret_ignore)
        set_value = Sig('in', 'in')
        static_value = Sig(use_handle=False)


def test_add():
    assert NiceFoo.add(2, 2) == 4


def test_static_method():
    item = NiceFoo.Item()
    assert item.static_value() == 5
