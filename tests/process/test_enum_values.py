import re
from util import local_fpath
from nicelib.process import process_headers


def test_func_macro():
    hinfo = process_headers(local_fpath(__file__, 'enum/func-macro.h'))
    assert re.search(r"X\s*=\s*256", hinfo.header_src)
    assert re.search(r"Y\s*=\s*512", hinfo.header_src)
    assert re.search(r"Z\s*=\s*0", hinfo.header_src)
