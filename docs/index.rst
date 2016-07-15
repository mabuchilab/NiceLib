NiceLib
=======

NiceLib is a Python library for rapidly developing "nice" basic wrappers for calling C libraries,
using ``cffi``. To see examples of it being used in the wild, check out `Instrumental
<https://github.com/mabuchilab/Instrumental>`_.

It lets you rapidly wrap a C function like this

.. code-block:: c

    int my_c_function(int arg1, float arg2, uint* out_arr, int out_arr_size, int reserved);

into a Python function that can be called like this ::

    out_buf = my_c_function(arg1, arg2)

just by defining a signature like this ::

    class MyLib(NiceLib):
        ...
        my_c_function = ('in', 'in', 'arr', 'len', 'ignore')

while giving you easy error handling and more.


Introduction
------------

NiceLib essentially consists of two layers:

* Tools for directly using headers to generate an importable Python module
* An interface for quickly and cleanly defining a Pythonic mid-level wrapped library

Mid-level means that functions take *input* arguments, return *output* arguments, and raise
Exceptions on error. NiceLib tries to simplify commonly-seen C idioms, like using user-created
buffers for returning output strings. Take, for example, this toy wrapper for the NIDAQmx library::

    class NiceNI(NiceLib):
        _info = load_lib('ni')
        _prefix = 'DAQmx'

        GetErrorString = ('in', 'buf', 'len')

Now, we can simply call ``NiceNI.GetErrorString(code)``, which is equivalent to the following::

    def GetErrorString(code):
        buflen = 512
        buf = ffi.new('char[]', buflen)
        ret = lib.DAQmxGetErrorString(code, buf, buflen)
        if ret != 0:
            raise DAQError(ret)
        return ffi.string(buf)

Many of our C library's functions may use status codes as their return value. To automatically
check the return code and raise an exception if warranted, we can use `err_wrap`::

    class NiceNI(NiceLib):
        ...
        def _err_wrap(retval):
            if retval != 0:
                raise DAQError(retval)

Often a C library will have method-like functions, each of which take a handle as its first
argument. These translate naturally into Python objects, obviating you of the need to pass the
handle all the time. For example, here's a partial definition of a Task object, again wrapping
NIDAQmx::

    class NiceNI(NiceLib):
        ...
        CreateTask = ('in', 'out')

        Task = NiceObjectDef(init=CreateTask, attrs={
            'StartTask': ('in'),
            'ReadAnalogScalarF64': ('in', 'in', 'out', 'ignore'),
        })

For both of these function signatures, the first *in* argument is the Task handle. We can then use
the class to make and use `Task` objects::

    task = NiceNI.Task('myTask')
    task.StartTask()

By specifying `init` when defining `Task`, the string `'myTask'` is passed to `NiceNI.CreateTask`,
whose return value (a task handle) is stored in the `Task` instance.


Automatically Processing Headers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The awesome `cffi` package greatly improves wrapping C libraries in Python by allowing you to load
header files directly, instead of manually churning out mind-numbing `ctypes` boilerplate.  However
it's not perfect---in particular, it makes only a feeble attempt at preprocessing header files,
meaning that in any non-trivial case you'll have to preprocess them yourself, either manually or by
running e.g.  the gcc preprocessor (`cffi` currently won't even handle a ``#define`` of a negative
constant!).  NiceLib provides preprocessing facilities that aim to allow you to use unmodified
header files to generate a "compiled" ffi module, without requiring a C compiler.

NiceLib's preprocessor has basic support for both object-like and (simple) function-like macros,
which it translates into equivalent [#]_ portable Python source code. For example

.. code-block:: c

    #define CONST_VAL       (1 << 4) | (1 << 1)
    #define LTZ(val)        ((val) < 0)

becomes the Python code::

    CONST_VAL = (1 << 4) | (1 << 1)
    def LTZ(val):
        return (val) < 0

The preprocessor also supports conditionals (``#ifdef`` and friends), ``#include`` s, and
platform-specific predefined macros (like ``__linux__``, ``__WIN64``, and ``__x86_64``).

Currently, ``#pragma`` directives are ignored.




.. [#] Note that, due to the nature of the C preprocessor, this generated code cannot always be
       truly equivalent. However, in the overwhelming majority of cases, the macros defined in
       library header files are quite simple.


User Guide
----------

.. toctree::
   :maxdepth: 2

   api
   wrapping
