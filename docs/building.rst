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

    lib_names = {'win*': 'foo'}


    def build():
        build_lib(header_info, lib_names, '_foolib', __file__)

You then call `load_lib('foo', __package__)` in your wrapper file to load the `LibInfo` object.
This uses the `_foolib` submodule if it exists. If it doesn't exist yet, `load_lib()` tries to
build it by calling the `build()` function in `_build_foo`. This calls `build_lib`, which searches
for `foo.dll` in the system path and looks for `foo.h` in both of the vendor-specific directories
given above. If it finds them successfully, it then processes the header so that `cffi` can
understand it.

Locating Headers and Libraries
------------------------------
Both the ``header_info`` and ``lib_name`` arguments to `build_lib` can be a dict that maps from a
platform to the corresponding path or name, allowing cross-platform support. The platform specifiers
(`'win*'` in the example above) are checked against `sys.platform` to find which platform-specific
paths and filenames to try, using pattern globbing if given. You may also discriminate between 32-
and 64-bit systems by appending a colon and then the bitness, e.g. `'win*:32'`. If you want the
platforms to be checked in a specific order, for example if you want to specify a default
fallthrough option, you can use an `ordereddict` instead of a `dict`.

For ``lib_name``, each platform-specific value is a string or tuple of strings. Each string is the
name of a library, without any prefix like `lib` or or suffix like `.so` or `.dll`. This is the form
used by `ctypes.util.find_library`. If you use a tuple of names, nicelib will look for each library
in turn, using the first one it finds. This is useful if the library could have any of a few
different names.

For ``header_info``, the each platform-specific value is a dict with the following keys:

'header'
    A string or tuple of strings which are the names/paths of all the headers to include.

'path'
    Optional. A tuple of base directories where the headers may be found. Each header is searched
    for in each directory until it is found. The directories are specified as strings.

Path strings can contain environment variables in the form `'{VAR_NAME}'` as shown in the example
above. If a variable is not contained in `os.environ`, the whole string is left unsubstituted.


Behind the Scenes
-----------------

`build_lib()` does a few things when it's executed. First, it looks for the header(s) in the
locations you've specified and invokes `process_headers()`, which preprocesses the headers and
returns two strings: the cleaned header C code and the extracted macros expressed as Python code.
It uses the cleaned header to generate an out-of-line `cffi` module, then appends code for loading
the shared lib and implementing the headers' macros. This finished module can be imported like any
other, but is usually loaded via `load_lib()`.

Processing Headers
""""""""""""""""""
The bulk of the heavy lifting is done (and most issues are most likely to occur) in
`process_headers()`. First, the header code is tokenized and parsed by a lexer and parser defined
in the `process` module. This parser doesn't understand C, but does understand the language of the
C preprocessor. It keeps track of macro definitions, removing them from the token stream and
performing expansion of macros when they are used. It also understands and obeys other directives,
including conditionals and ``#include``\s. After parsing, the token stream should be free of any
harmful directives that `pycparser`/`cffi` don't understand.

This token stream can then be acted upon by the so-called "token hooks", which can be supplied via
the arguments lists of `process_headers()` and `build_lib()`. These hooks are functions which
both accept and return a sequence of tokens. The purpose of each hook is to perform a specific
transformation on the token stream, usually removing nonstandard syntax that `pycparser`/`cffi` may
not understand (e.g. C++ specific syntax).

Once the hooks are all applied, the tokens are joined together into chunks that are parseable by
`pycparser`'s C parser. After each chunk is parsed, it is acted upon by the "AST hooks", which take
the parsed abstract syntax tree (AST) and a reference to the parser and return a transformed AST.
This allows hooks to modify the AST and the state of the parser. Once all of the chunks have been
parsed and joined together into one big AST, this tree is used to generate the C source code which
is later returned by `process_headers()`.
