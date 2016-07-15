Building A Module
=================

Before you can wrap your library, you first need to make it usable via `cffi`. Normally this would
involve preprocessing your headers via ``gcc -e``, followed by more cleaning by hand. Then you'd
have to distribute this header with your software, with possible copyright implications.

In an ideal world, you wouldn't have to distribute a header at all since the user has the library
and its headers installed already. NiceLib's goal is to make this ideal world a reality.

If all goes well, you need to do only one thing: write a build module. For a library named `foo`,
name your module file `_build_foo.py`, and put it in the same directory that your wrapper will be
in. This build file contains info about where to find the shared lib and its headers on different
platforms. The build module for a Windows-only lib might look like this::

    # _build_foo.py
    from nicelib import build_lib

    header_info = {
        'win*': {
            'path': (
                r"{PROGRAMFILES}\Vendor\Product",
                r"{PROGRAMFILES(X86)}\Vendor\Product",
            ),
            'header': 'foo.h'
        },
    }

    lib_names = {'win*': 'foo.dll'}


    def build():
        build_lib(header_info, lib_names, '_foolib', __file__)

You then call `load_lib('foo', __package__)` in your wrapper file to load the `LibInfo` object.
This uses the `_foolib` submodule if it exists. If it doesn't exist yet, `load_lib()` tries to
build it by calling the `build()` function in `_build_foo`. This searches for `foo.dll` in the
system path and looks for `foo.h` in both of the vendor-specific directories given above. If it
finds them successfully, it then processes the header so that `cffi` can understand it.

The platform specifiers (`'win*'` in this case) are checked against `sys.platform` to find which
platform-specific paths and filenames to try, using pattern globbing if given.
