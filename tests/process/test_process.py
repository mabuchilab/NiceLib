from util import local_fpath
from nicelib.process import process_headers


def test_exclude_sys_funcdefs():
    header_src, _ = process_headers(local_fpath(__file__, 'general/sys-funcdef-a.h'))
    assert 'program_func' in header_src
    assert 'created_func' in header_src
    assert 'sys_func' not in header_src
