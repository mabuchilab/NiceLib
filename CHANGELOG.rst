Change Log
==========

(0.4) - 2017-11-13
------------------

Added
"""""
- Support for searching for heaaders from multiple possible sets
- Automatic PyPI deployment via TravisCI

Changed
"""""""
- ``build_lib()`` is now silent by default
- Ignore bad or unsupported types during header processing


(0.3.1) - 2017-5-25
-------------------

Changes
"""""""
- Fix handling of lib paths
- Account for nonexistent attributes in FFI libs
- Fix handling of empty signature tuples
- Change error for missing functions into a warning


(0.3) - 2017-4-7
----------------

Added
"""""
- Inject ``funcname`` into ``ret``
- Support for Unicode headers
- Experimental support for specifying units that ``len`` sig handler uses
- Strip prefixes of enum constants too
- Allow searching for a lib under multiple names/locations
- New logo

Changed
"""""""
- Renamed ``ret_wrap`` to to ``ret`` for consistency
- Fixed handling of nested structs/unions/enums in ``struct_func_hook``
- Use only one ``cparser``. Speeds up parsing of large header sets dramatically
- Fixed ``init`` arg handling for ``NiceObjectDef``
- Fixed bug that prevented generation of func-like macros that had arguments


(0.2) - 2016-8-12
-----------------

Added
"""""
- Introduced ``load_lib``
- Introduce the ``LibInfo`` object and the ``_info`` NiceLib class attribute
- ``'bufout'`` argtype and ``'buf_free'`` setting
- ``'use_numpy'`` setting for wrapping output arrays
- 'Hooks' system for allowing user to hook into header processing at various points
- Allow specifying existing return-wrappers by name
- Binding auto-generation via ``generate_bindings()``
- Inject optional args into ``ret_wrap``
- Allow ignoring of various headers
- A bunch of tests

Changed
"""""""
- Renamed ``NiceObject`` to ``NiceObjectDef``
- Renamed ``_err_wrap`` to ``_ret_wrap``
- Renamed ``_lib`` to ``__ffilib``
- Fixed silly, horrible release bug that broke almost all wrapping of args
- Preprocessor now recognizes same common types as ``cffi``
- Prevent redefinition of struct/union/enum typedefs due to ``pycparser``
- Build and load lib using the correct directories
- Standardized settings/flags to be consistent across scopes
- Parse C code in chunks
- Fixed lexing of some missing and nonstandard tokens
- Some lexing performance improvements
- Keep unwrapped ffi funcs out of ``dir(NiceFoo)``
- Improved error output


(0.1) - 2016-6-29
-----------------

Added
"""""
- Python2/3 compatibility via ``future``
- Support for ``#include``, ``#error``, and ``#warning`` directives
- ``NiceObject`` s
- Convenient ``build_lib()`` function
- Platform-specific macros/settings
- New signature types 'arr' and 'ignore'
- Support for ``numpy`` ``ndarray`` s
- Basic documentation
- Initial unit-tests and Travis CI support
- Support for calculated enum values
- Basic support for wrapping variadic functions

Changed
"""""""
- Spun off ``NiceLib`` from ``Instrumental``
