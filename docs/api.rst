API Documentation
=================

These are the major NiceLib classes and functions of which you should know:

* :ref:`Header-API`

  * `build_lib()`
  * `process_headers()`
  * :ref:`Token-Hooks`

    * `cdecl_hook()`
    * `stdcall_hook()`
    * `declspec_hook()`
    * `inline_hook()`
    * `extern_c_hook()`
    * `enum_type_hook()`
    * `asm_hook()`
    * `vc_pragma_hook()`
    * `struct_func_hook()`
    * `add_line_directive_hook()`

  * :ref:`Token-Helpers`

    * `remove_pattern()`
    * `modify_pattern()`
    * `ParseHelper`

  * :ref:`AST-Hooks`

    * `add_typedef_hook()`

  * :ref:`AST-Helpers`

    * `TreeModifier`

* :ref:`wrapper-API`

  * `NiceLib`
  * `NiceObjectDef`
  * `load_lib()`
  * `generate_bindings()`


.. _Header-API:

Header Processing API
---------------------
.. autofunction:: nicelib.build_lib
.. autofunction:: nicelib.process.process_headers


.. _Token-Hooks:

Token Hooks
~~~~~~~~~~~
These functions can all be used in the `token_hooks` passed to `build_lib()` or `process_headers()`

.. autofunction:: nicelib.process.cdecl_hook
.. autofunction:: nicelib.process.stdcall_hook
.. autofunction:: nicelib.process.declspec_hook
.. autofunction:: nicelib.process.inline_hook
.. autofunction:: nicelib.process.extern_c_hook
.. autofunction:: nicelib.process.enum_type_hook
.. autofunction:: nicelib.process.asm_hook
.. autofunction:: nicelib.process.vc_pragma_hook
.. autofunction:: nicelib.process.struct_func_hook
.. autofunction:: nicelib.process.add_line_directive_hook

.. _Token-Helpers:

Token Hook Helpers
~~~~~~~~~~~~~~~~~~
These functions and classes are useful for writing your own custom token hooks:

.. autofunction:: nicelib.process.remove_pattern
.. autofunction:: nicelib.process.modify_pattern
.. autoclass:: nicelib.process.ParseHelper
    :members:


.. _AST-Hooks:

AST Hooks
~~~~~~~~~

.. automethod:: nicelib.process.add_typedef_hook


.. _AST-Helpers:

AST Hook Helpers
~~~~~~~~~~~~~~~~

.. autoclass:: nicelib.process.TreeModifier
    :members:

.. _Wrapper-API:

Mid-Level Binding API
---------------------
.. autoclass:: nicelib.nicelib.NiceLib
    :members:
    :undoc-members:

.. autoclass:: nicelib.nicelib.NiceObjectDef
    :members:
    :undoc-members:

.. autofunction:: nicelib.load_lib

.. autofunction:: nicelib.generate_bindings
