from nicelib import build_lib


header_paths = {'linux*': {'header': 'foo.h'}}
lib_names = {'linux*': 'libfoo.so'}


def build():
    build_lib(header_paths, lib_names, '_foolib', __file__)


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    build()
