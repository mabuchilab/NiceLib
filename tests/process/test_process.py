from util import local_fpath
from nicelib.process import process_headers


def test_exclude_sys_funcdefs():
    header_src, _, _ = process_headers(local_fpath(__file__, 'general/sys-funcdef-a.h'))
    assert 'program_func' in header_src
    assert 'created_func' in header_src
    assert 'sys_func' not in header_src


def test_argnames():
    _, _, argnames = process_headers(local_fpath(__file__, 'general/argnames.h'))
    assert argnames['f'] is None
    assert argnames['f_void'] == []
    assert argnames['f_int'] == [None]
    assert argnames['f_int_int'] == [None, None]

    assert argnames['f_inta'] == ['a']
    assert argnames['f_inta_intb'] == ['a', 'b']

    assert argnames['f_ptra'] == ['a']
    assert argnames['f_arra'] == ['a']

    assert argnames['f_structa'] == ['a']
    assert argnames['f_structptra'] == ['a']
