from nicelib import NiceLib, load_lib, Sig, NiceObject, ret_ignore, ret_return


class NiceFoo(NiceLib):
    """Foo library"""
    _info = load_lib('foo', pkg=None, dir=__file__)
    _ret = ret_return

    @Sig('in', 'in')
    def add(cls, a, b):
        return cls._autofunc_add(a, b)

    create_item = Sig()

    class Item(NiceObject):
        _init_ = 'create_item'
        _prefix_ = 'item_'

        get_id = Sig('in')
        get_value = Sig('in', ret=ret_ignore)
        set_value = Sig('in', 'in')


def test_add():
    assert NiceFoo.add(2, 2) == 4
