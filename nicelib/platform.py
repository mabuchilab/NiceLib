# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz

# Info about macros defined here can be found at this great reference:
# https://sourceforge.net/p/predef/wiki/Home/

import sys
import glob
import itertools
from fnmatch import fnmatch

__all__ = ['PREDEF_MACRO_STR', 'INCLUDE_DIRS']

is_64bit = sys.maxsize > 2**32

if fnmatch(sys.platform, 'linux*'):
    PREDEF_MACRO_STR = """
        #define unix 1
        #define __unix 1
        #define __unix__ 1
        #define linux 1
        #define __linux 1
        #define __linux__ 1
        #define __gnu_linux__ 1
        #define __STDC__ 1
    """
    INCLUDE_DIRS = ['/usr/include', '/usr/local/include', '/usr/lib/gcc/*/*/include']
    COMPILER = 'GCC'

elif fnmatch(sys.platform, 'darwin*'):
    PREDEF_MACRO_STR = """
        #define __APPLE__ 1
    """
    INCLUDE_DIRS = ['/usr/include', '/usr/local/include']
    COMPILER = 'GCC'

elif fnmatch(sys.platform, 'win*'):
    PREDEF_MACRO_STR = """
        #define _WIN32 1
    """

    if is_64bit:
        PREDEF_MACRO_STR += """
            #define _WIN64
        """
    COMPILER = 'MSVC'

else:
    raise Exception("Currently unsupported platform '{}'".format(sys.platform))


if COMPILER == 'GCC':
    if is_64bit:
        PREDEF_MACRO_STR += """
            #define __amd64 1
            #define __amd64__ 1
            #define __x86_64 1
            #define __x86_64__ 1
        """
    else:
        PREDEF_MACRO_STR += """
            #define i386 1
            #define __i386 1
            #define __i386__ 1
        """
elif COMPILER == 'MSVC':
    if is_64bit:
        PREDEF_MACRO_STR += """
            #define _M_IX86
        """
    else:
        PREDEF_MACRO_STR += """
            #define _M_X64
            #define _M_AMD64
        """


# Glob the include dirs into a flattened list
INCLUDE_DIRS = list(itertools.chain(*(glob.glob(d) for d in INCLUDE_DIRS)))
