from util import local_fpath
from nicelib.process import process_headers


def test_pragma_once():
    hinfo = process_headers(local_fpath(__file__, 'pragma/once-a.h'))
    assert hinfo.header_src.count('123') == 1
