from nicelib import build_lib


header_paths = {'linux*': {'header': 'enum.h'}}
lib_names = {'linux*': 'libenum.so'}


def build():
    build_lib(header_paths, lib_names, '_enumlib', __file__)


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    build()
