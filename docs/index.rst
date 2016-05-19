NiceLib
=======

NiceLib is a Python library for rapidly developing "nice" basic wrappers for calling C libraries,
using ``cffi``. To see examples of it being used in the wild, check out `Instrumental
<https://github.com/mabuchilab/Instrumental>`_.

It essentially consists of two layers: first, tools for directly using headers to generate an
importable Python module; second, an interface for quickly and cleanly defining a Pythonic
mid-level wrapped library. Mid-level means that you pass in only the input arguments, the outputs
are returned directly, and errors cause Exceptions. NiceLib tries to simplify commonly-seen C
idioms, like using user-created buffers for returning output strings. Take, for example, this
toy wrapper for the NIDAQmx library::

    class NiceNI(NiceLib):
        _ffi = ffi
        _lib = lib
        _defs = defs
        _prefix = ('DAQmx_', 'DAQmx')
        _buflen = 512

        def _err_wrap(ret_code):
            if ret_code != 0:
                raise DAQError(ret_code)

        GetErrorString = ('in', 'buf', 'len')

Now, we can simply call ``NiceNI.GetErrorString(code)``, which is equivalent to the following::

    def GetErrorString(code):
        buflen = 512
        buf = ffi.new('char[]', buflen)
        ret = lib.DAQmxGetErrorString(code, buf, buflen)
        if ret != 0:
            raise DAQError(ret)
        return ffi.string(buf)

Often a library will have sets of method-like functions, which takes one or more handles as its
first args. These translate naturally into Python objects, obviating you of the need to pass the
handle all the time. For example, here's a partial definition of a Task object, again wrapping
NIDAQmx::

    class NiceNI(NiceLib):
        ...
        CreateTask = ('in', 'out')

        Task = NiceObject({
            'StartTask' = ('in'),
            'ReadAnalogScalarF64' = ('in', 'in', 'out', 'ignore'),
        })

For both of these function signatures, the first *in* argument is the Task handle. We can then use
the class to make and use ``Task`` objects::

    handle = NiceNI.CreateTask('')
    task = NiceNI.Task(handle)
    task.StartTask()


``cffi`` greatly improves wrapping C libraries in Python, by allowing you to load header files
directly, instead of writing mind-numbing ctypes boilerplate. However it's not perfect---in
particular, it makes only a feeble attempt at preprocessing header files, meaning that in any
non-trivial case you'll have to preprocess them yourself, either manually or by running e.g. the
gcc preprocessor (it currently won't even handle a ``#define`` of a negative constant!). NiceLib
provides preprocessing facilities that aim to allow you to use unmodified header files to generate
a "compiled" ffi module, without requiring a C compiler.

NiceLib's preprocessor has basic support for both object-like and (simple) function-like macros,
which it translates into equivalent[#]_ portable Python source code. For example

.. code-block:: c

    #define CONST_VAL       (1 << 4) | (1 << 1)
    #define LTZ(val)        ((val) < 0)

becomes the Python code::

    CONST_VAL = (1 << 4) | (1 << 1)
    def LTZ(val):
        return (val) < 0

The preprocessor also supports conditionals (``#ifdef`` and friends), and the ultimate goal is to
support platform-specific predefined macros (like ``__linux__`` and ``__WIN64``).

Currently, the ``#include`` and ``#pragma`` directives are ignored.




.. [#] Note that, due to the nature of the C preprocessor, this generated code cannot always be
       truly equivalent. However, in the overwhelming majority of cases, the macros defined in
       library header files are quite simple.



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
