from util import local_fpath
from nicelib.process import process_headers


def test_pragma_once():
    header_src, _ = process_headers(local_fpath(__file__, 'pragma/once-a.h'))
    assert header_src.count('123') == 1
