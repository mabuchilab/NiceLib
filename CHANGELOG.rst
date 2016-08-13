Change Log
==========

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
