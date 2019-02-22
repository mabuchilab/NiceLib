import re
from util import local_fpath
from nicelib.process import process_headers


def test_func_macro():
    hinfo = process_headers(local_fpath(__file__, 'enum/func-macro.h'))
    assert re.search(r"X\s*=\s*256", hinfo.header_src)
    assert re.search(r"Y\s*=\s*512", hinfo.header_src)
    assert re.search(r"Z\s*=\s*0", hinfo.header_src)


def test_enum():
    hinfo = process_headers(local_fpath(__file__, 'enum/basic.h'))

    e0 = hinfo.enums[0]
    assert e0.tag_name is None
    assert e0.typedef_names == []
    assert e0.value_names == ['anon1', 'anon2', 'anon3']

    e1 = hinfo.enums[1]
    assert e1.tag_name == 'TagOnly'
    assert e1.typedef_names == []
    assert e1.value_names == ['tagOnlyVal1', 'tagOnlyVal2']

    e2 = hinfo.enums[2]
    # Note that autotagging keeps tag_name from being None here
    assert e2.typedef_names == ['TypedefOnly']
    assert e2.value_names == ['typedefOnlyVal1', 'typedefOnlyVal2']

    e3 = hinfo.enums[3]
    assert e3.tag_name == 'EnumTag'
    assert e3.typedef_names == ['EnumType']
    assert e3.value_names == ['bothVal1', 'bothVal2']

    e4 = hinfo.enums[4]
    # Note that autotagging keeps tag_name from being None here
    assert e4.typedef_names == ['EnumA', 'EnumB', 'EnumC']
    assert e4.value_names == ['multiVal1', 'multiVal2']
