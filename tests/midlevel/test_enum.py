from nicelib import NiceLib, load_lib


class NiceEnumLib(NiceLib):
    _info_ = load_lib('enum', pkg=None, dir=__file__)


def test_enums():
    assert hasattr(NiceEnumLib.enums, 'MyEnum')
    MyEnum = NiceEnumLib.enums.MyEnum
    assert MyEnum.Val_First.value == 0
    assert MyEnum.Val_Second.value == 5
    assert MyEnum.Val_Last == MyEnum.Val_Second
