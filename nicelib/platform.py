# -*- coding: utf-8 -*-
# Copyright 2016-2017 Nate Bogdanowicz

# Info about macros defined here can be found at this great reference:
# https://sourceforge.net/p/predef/wiki/Home/

import os
import sys
import glob
import logging
from fnmatch import fnmatch

__all__ = ['PREDEF_MACRO_STR', 'INCLUDE_DIRS']
log = logging.getLogger(__name__)

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
    INCLUDE_DIRS = ['/usr/include',
                    '/usr/lib/gcc/*/*/include-fixed',
                    '/usr/local/include',
                    '/usr/lib/gcc/*/*/include']
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
    INCLUDE_DIRS = [r'{PROGRAMFILES}\Windows Kits\*\Include\*',
                    r'{PROGRAMFILES}\Windows Kits\*\Include\*\*',
                    r'{PROGRAMFILES}\Windows Kits\*\Include\*\*\*',
                    r'{PROGRAMFILES}\Microsoft Visual Studio *\VC\include',
                    r'{PROGRAMFILES}\Microsoft Visual Studio *\VC\include\*',
                    r'{PROGRAMFILES}\Microsoft Visual Studio *\VC\include\*\*',
                    r'{PROGRAMFILES(X86)}\Windows Kits\*\Include\*',
                    r'{PROGRAMFILES(X86)}\Windows Kits\*\Include\*\*',
                    r'{PROGRAMFILES(X86)}\Windows Kits\*\Include\*\*\*',
                    r'{PROGRAMFILES(X86)}\Microsoft Visual Studio *\VC\include',
                    r'{PROGRAMFILES(X86)}\Microsoft Visual Studio *\VC\include\*',
                    r'{PROGRAMFILES(X86)}\Microsoft Visual Studio *\VC\include\*\*',
                    r'{PROGRAMFILES(X86)}\Microsoft Visual Studio\*\Community\VC\Tools\MSVC\*\include']

    if is_64bit:
        PREDEF_MACRO_STR += """
            #define _WIN64
        """
    COMPILER = 'MSVC'

else:
    raise Exception("Currently unsupported platform '{}'".format(sys.platform))


if COMPILER == 'GCC':
    REPLACEMENT_MAP = []
    PREDEF_MACRO_STR += "\n#define __builtin_va_list void*"
    if is_64bit:
        PREDEF_MACRO_STR += """
            #define __amd64 1
            #define __amd64__ 1
            #define __x86_64 1
            #define __x86_64__ 1
            #define __GNUC__ 1
        """
    else:
        PREDEF_MACRO_STR += """
            #define i386 1
            #define __i386 1
            #define __i386__ 1
            #define __GNUC__ 1
        """
elif COMPILER == 'MSVC':
    # Ordered by precedence - should usually be longest match first
    REPLACEMENT_MAP = [
        (['unsigned', '__int8'], 'uint8_t'),
        (['signed', '__int8'], 'int8_t'),
        (['__int8'], 'int8_t'),
        (['unsigned', '__int16'], 'uint16_t'),
        (['signed', '__int16'], 'int16_t'),
        (['__int16'], 'int16_t'),
        (['unsigned', '__int32'], 'uint32_t'),
        (['signed', '__int32'], 'int32_t'),
        (['__int32'], 'int32_t'),
        (['unsigned', '__int64'], 'uint64_t'),
        (['signed', '__int64'], 'int64_t'),
        (['__int64'], 'int64_t'),
    ]

    if is_64bit:
        PREDEF_MACRO_STR += """
            #define _M_IX86
        """
    else:
        PREDEF_MACRO_STR += """
            #define _M_X64
            #define _M_AMD64
        """


def fill_and_glob_dirs(dir_templates):
    dirs = []
    for dir_template in dir_templates:
        try:
            filled_dir = dir_template.format(**os.environ)
        except KeyError as e:
            # Log instead of warn b/c this gets run every time nicelib is imported, and we trust
            # the INCLUDE_DIRS defined in this file. If this function ever gets used by other
            # code, it might be worthwhile to add a 'warn_missing' option
            log.info("os.environ does not provide key '%s'", e.args[0])
            continue

        dirs.extend(glob.glob(filled_dir))
    return dirs


# Glob the include dirs into a flattened list
INCLUDE_DIRS = fill_and_glob_dirs(INCLUDE_DIRS)
