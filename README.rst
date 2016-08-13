.. image:: https://travis-ci.org/mabuchilab/NiceLib.svg?branch=master
    :target: https://travis-ci.org/mabuchilab/NiceLib
    :alt: Travis CI


|logo| NiceLib
==============

NiceLib is a package for rapidly developing "nice" Python bindings to C libraries, using ``cffi``.

NiceLib accomplishes this in two main ways: first, it converts header files (macros and all) into a
format usable by ``cffi`` (i.e. it preprocesses them); second, it provides an API for quickly and
cleanly defining pythonic mid-level interfaces that wrap low-level libraries.

For install information, documentation, examples, and more, see our page on
`ReadTheDocs <http://nicelib.readthedocs.org/>`_.


.. |logo| image:: images/nicelib-logo-small.png
    :alt: NiceLib
    :height: 50
