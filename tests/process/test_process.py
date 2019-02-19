from util import local_fpath
from nicelib.process import process_headers


def test_exclude_sys_funcdefs():
    hinfo = process_headers(local_fpath(__file__, 'general/sys-funcdef-a.h'))
    assert 'program_func' in hinfo.header_src
    assert 'created_func' in hinfo.header_src
    assert 'sys_func' not in hinfo.header_src


def test_argnames():
    hinfo = process_headers(local_fpath(__file__, 'general/argnames.h'))
    assert hinfo.argnames['f'] is None
    assert hinfo.argnames['f_void'] == []
    assert hinfo.argnames['f_int'] == [None]
    assert hinfo.argnames['f_int_int'] == [None, None]

    assert hinfo.argnames['f_inta'] == ['a']
    assert hinfo.argnames['f_inta_intb'] == ['a', 'b']

    assert hinfo.argnames['f_ptra'] == ['a']
    assert hinfo.argnames['f_arra'] == ['a']

    assert hinfo.argnames['f_structa'] == ['a']
    assert hinfo.argnames['f_structptra'] == ['a']
