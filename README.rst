.. image:: https://travis-ci.org/mabuchilab/NiceLib.svg?branch=master
    :target: https://travis-ci.org/mabuchilab/NiceLib
    :alt: Travis CI


|logo| NiceLib
==============

NiceLib is a package for rapidly developing "nice" Python bindings to C libraries, using ``cffi``.

NiceLib accomplishes this in two main ways: first, it converts header files (macros and all) into a
format usable by ``cffi`` (i.e. it preprocesses them); second, it provides an API for quickly and
cleanly defining pythonic mid-level interfaces that wrap low-level libraries.

For further information, documentation, examples, and more, see our page on
`ReadTheDocs <http://nicelib.readthedocs.org/>`_.

For contributing, reporting issues, and providing feedback, see our
`GitHub page <https://github.com/mabuchilab/NiceLib>`_.


Installing
----------

NiceLib is available on PyPI::

    $ pip install nicelib

If you would like to use the development version, download and extract a zip of the source from our
`GitHub page <https://github.com/mabuchilab/NiceLib>`_ or clone it using git. Now install::

    $ cd /path/to/NiceLib
    $ pip install .


.. |logo| image:: images/nicelib-logo-small.png
    :alt: NiceLib
    :height: 50
