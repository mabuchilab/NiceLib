import re
from util import local_fpath
from nicelib.process import process_headers


def test_func_macro():
    header_src, _ = process_headers(local_fpath(__file__, 'enum/func-macro.h'))
    assert re.search(r"X\s*=\s*256", header_src)
    assert re.search(r"Y\s*=\s*512", header_src)
    assert re.search(r"Z\s*=\s*0", header_src)
