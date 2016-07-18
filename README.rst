.. image:: https://travis-ci.org/mabuchilab/NiceLib.svg?branch=master
    :target: https://travis-ci.org/mabuchilab/NiceLib
    :alt: Travis CI


|logo| NiceLib
==============

NiceLib is a Python library for rapidly developing "nice" basic wrappers for calling C libraries,
using ``cffi``. Essentially, it lets you take a C shared library (.dll or .so) and its headers and
rapidly create a nice pythonic interface.

NiceLib accomplishes this in two main ways: first, it converts header files (macros and all) into a
format usable by ``cffi`` (i.e. it preprocesses them); second, it provides an API for quickly and
cleanly defining pythonic mid-level interfaces that wrap low-level libraries.

For install information, documentation, examples, and more, see our page on
`ReadTheDocs <http://nicelib.readthedocs.org/>`_.


.. |logo| image:: images/nicelib-logo.svg
    :alt: NiceLib
    :height: 50
