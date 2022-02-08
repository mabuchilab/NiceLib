from nicelib import build_lib


header_paths = {'linux*': {'header': 'bar.h'}}
lib_names = {'linux*': 'libbar.so'}


def build():
    build_lib(header_paths, lib_names, '_bar2lib', __file__)


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    build()
