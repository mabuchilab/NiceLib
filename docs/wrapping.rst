Creating Mid-Level Bindings
===========================

`NiceLib` is the base class that provides a nice interface for quickly defining mid-level library
bindings. You define a subclass for each specific library (DLL) you wish to wrap.  `NiceLib`'s
metaclass then converts your specification into a wrapped library. You use this subclass directly,
without instantiating it.

It's worth discussing what we mean by "mid-level" bindings. Mid-level bindings have a one-to-one
correspondence between low-level functions and mid-level functions. The difference is that each
mid-level function has a more Pythonic interface that lets the user mostly or entirely avoid working
with `cffi` directly. In other words, the overall structure of the library stays the same, but each
individual function's interface may change.

These mid-level bindings can then be used to craft high-level bindings that might have a completely
different structure than the underlying low-level library.

Let's say we want to wrap a motor-control library and its header looks something like this:

.. code-block:: c

    // Example header file
    typedef void* HANDLE;

    int GeneralGetDeviceList(uint* devList, uint listSize);
    void GeneralGetErrorString(int errCode, char *recvBuf, uint bufSize);
    int GeneralOpenMotor(uint motorID, HANDLE *phMotor);

    int MotorClose(HANDLE hMotor);
    int MotorMoveTo(HANDLE hMotor, long pos);
    int MotorGetPosition(HANDLE hMotor, long *pPos);
    int MotorGetSerial(HANDLE hMotor, char *recvBuf, uint bufSize);


We would then write bindings like this::

    from nicelib import NiceLib, NiceObjectDef, load_lib

    class NiceMotor(NiceLib):
        _info = load_lib('awesomemotor', __package__)
        _ret = 'code'

        def _ret_code(retval):
            if retval != 0:
                raise MotorError(NiceMotor.GetErrorString(retval))

        _prefix = 'General'
        GetDeviceList = ('arr', 'len=20')
        GetErrorString = ('in', 'buf', 'len', {'ret': 'ignore'})
        OpenMotor = ('in', 'out')

        Motor = NiceObjectDef(prefix='Motor', init='OpenMotor', attrs=dict(
            Close = ('in'),
            MoveTo = ('in', 'in'),
            GetPosition = ('in', 'out'),
            GetSerial = ('in', 'buf', 'len=64'),
        ))

Then we can use the library like this::

    motor_ids = NiceMotor.GetDeviceList()

    for motor_id in motor_ids:
        motor = NiceMotor.Motor(motor_id)
        pos = motor.GetPosition()
        serial = motor.GetSerial()
        print("Motor {} is at position {}".format(serial, pos))
        motor.Close()

There are a number of features in use in this example: prefix removal, return value wrapping, array
and string buffer output, and `NiceObjectDef`\s with custom initializers. These make use of
settings, which you can read more about below.

Settings
--------
Settings, also called flags, give you extra control over how a library is wrapped. Settings are
scoped, meaning that you can specify them class-wide, NiceObject-wide, and per-function. For
example:

**Class-level**:
Give the class an attribute with the setting name prefixed by an underscore::

   class MyLib(NiceLib):
       _buflen = 128

**NiceObject-level**: 
Pass settings as keyword args to the `NiceObjectDef` constructor::

   MyObject = NiceObjectDef(buflen=128, ...)

**Function-level**:
Append a dict to the end of the function's signature tuple::

   MyFunction = ('in', 'in', 'out', {'buflen': 128})


The available settings are:

prefix
    A `str` or sequence of `str`\s specifying prefixes to strip from the library function
    names. For example, if the library has functions named like ``SDK_Func()``, you can set
    `_prefix` to `'SDK_'`, and access them as ``Func()``. If more than one prefix is given, they are
    tried in order for each signature until the appropraite function is found. The empty prefix
    ``''`` is always tried. Sometimes you may want to specify one library-wide prefix and a
    different per-object prefix, as done in the above example.

    These prefixes also get stripped from macro names and enum constants, if applicable.

ret
    A function or `str` specifying a handler function to handle the return values of each library
    function. See :ref:`retval-handlers` for details.

buflen
    An `int` specifying the default length for buffers and arrays. This can be overridden on a
    per-argument basis in the argument's spec string, e.g. `'len=64'` will make a 64-character
    buffer or a 64-element array.

free_buf
    A function that is called on the pointer returned for 'bufout' argtypes, used for freeing their
    associated memory. It is called immediately after the buffer is copied to produce a Python
    string. It is not called if a null pointer is returned. May be None.

use_numpy
    If True, convert output args marked as `'arr'` to numpy arrays. Requires numpy to be
    installed.

struct_maker
    A function that is called to create an FFI struct of the given type. Mainly useful for odd
    libraries that require you to always fill out some field of the struct, like its size in bytes.


Class Attributes
----------------
NiceLib makes use of a few underscore-prefixed special class attributes. In addition to class-wide
settings, as described above, they include:

_info
    A `LibInfo` object that contains access to the underlying library and macros. Required
    (unless you are using the old-style `_ffi`, `_ffilib`, and `_defs` attributes)

Typically you will want to pass the relevant library attributes via a `LibInfo` instance created
via :py:func:`~nicelib.load_lib`. However, it is currently possible to specify them directly. This
was the original method, and may become deprecated in later versions of `NiceLib`.

_ffi
    FFI instance variable. Required if not using `_info`.

_ffilib
    FFI library opened with `dlopen()`. Required if not using `_info`.

_defs
    ``dict`` containing the Python-equivalent macros defined in the header file(s). Optional and
    only used if not using `_info`.


Function Signatures
-------------------

Function signatures are specified as (non-underscore-prefixed) class attributes. Each signature
consists of a tuple defining the input-output signature of the underlying C function. The last
element of the tuple may be an optional ``dict`` specifying any per-function flags, like custom
return value handling.

It's important to note that the sig tuple is designed to closely match the signature of the C
function, i.e. they have the same number of items (except for the optional flag dict). This makes it
clearer what each element corresponds to.

The basic idea behind signature specifications is to handle input and output in a more Pythonic
manner---inputs get passed in via a function's arguments, while its outputs get returned as part of
the function's return values. Take the simple example from above::

    OpenMotor = ('in', 'out')

This says that the C-function's first argument (``uint motorID``) is used strictly as input, and
its second argument (``HANDLE *phMotor``) is used strictly as output---the function takes an ID
number and returns a handle to a newly opened motor. Using this signature allows us to call the
function more naturally as ``handle = OpenMotor(motorID)``.

The available signature values are:

'in'
    The argument is an input and gets passed into the mid-level function.

'out'
    The argument is an output. It is not passed into the mid-level function, but is instead added to
    the list of return values. NiceLib automatically allocates an appropriate data structure, passes
    its address-pointer to the C function, uses the dereferenced result as the return value.

    This can't be used for `void` pointers, since there's no way to know what to allocate, or what
    type to return.

'inout'
    The argument is used as both input and output. The mid-level function takes it as an argument
    and also returns it with the return values. You can pass in either a value or a pointer to the
    value. For example, if the underlying C argument is an ``int *``, you can pass in a `cffi` int
    pointer, which will be used directly, or (more typically) you can pass in a Python int, which
    will be used as the initial value of a newly-created `cffi` int pointer.

'bufout'
    The argument is a pointer to a string buffer (a ``char**``). This is used for when the C
    library creates a string buffer and returns it to the user. NiceLib will automatically convert
    the output to a Python `bytes`, or None if a null pointer was returned.

    If the memory should be cleaned up by the user (as is usually the case), you may use the
    `free_buf` setting to specify the cleanup function.

'buf'
    The argument is a string buffer used for output. The C argument is a ``char`` pointer or array,
    into which the C-function writes a null-terminated string. This string is decoded using
    `ffi.string()`, and added to the return values.

    This is used for the common case of a C function which takes both a string buffer and its
    length as inputs, so that it doesn't overrun the buffer. As such, `'buf'` requires a
    corresponding `'len'` entry. The first `'buf'`/`'arr'` is matched with the first `'len'` and so
    forth. If don't need to pass in a length parameter to the C-function, use `'buf[n]'` as
    described below.

    NiceLib will automatically create the buffer and pass it and the length parameter to the
    C-function. You simply receive the `bytes`.

'buf[n]'
    The same as `'buf'`, but does not have a matching `'len'`. Because of this, the buffer length
    is specified directly as an int. For example, a 20-char buffer would be `'buf[20]'`.

'arr'
    The same as `'buf'`, but does not call `ffi.string()` on the returned value. Used e.g. for
    `int` arrays.

'arr[n]'
    The same as `'buf[n]'`, but does not call `ffi.string()` on the returned value. Used e.g. for
    ``int`` arrays.

'len'
    The length of the buffer being passed to the C-function. See `'buf'` for more info. This will
    use the length given by the innermost `buflen` setting.
    
'len=n'
    The same as `'len'`, but with an overridden length. For example, `'len=32'` would allocate a
    buffer or array of length 32, regardless of what `buflen` is.

'len=in'
    Similar to `'len=n'`, except the mid-level function takes an input argument which is an
    ``int`` specifying the size of buffer that should be allocated for that invocation.

'ignore'
    Ignore the argument, passing in 0 or NULL, depending on the arg type. This is useful for
    functions with "reserved" arguments which don't do anything.


.. _retval-handlers:

Return Value Handlers
---------------------
Return value handlers are specified via the ``ret`` flag. Each handler is either a function or `str`
specifying a function to handle the return values of each library function. For example, they can be
used to raise exceptions or return values. They can even do custom handling based on what args were
passed to the function.

A handler function takes the C function's return value, often an error/success code, as its first
argument (see below for other optional parameters it may take). If the handler returns a non-None
value, it will be appended to the wrapped function's return values.

If you define a function `_ret_foo()` in your subclass, you may refer to it by using the string
`'foo'`. This works for any function defined in the class body that has a name starting with
``_ret_``, including builtin handlers.

Builtin Handlers
~~~~~~~~~~~~~~~~
There are two handlers that `NiceLib` defines for convenience:

_ret_return
    The default handler. Simply appends the return value to the wrapped function's return values.

_ret_ignore
    Ignores the value entirely and does not return it. Useful for ``void`` functions


Injected Parameters
~~~~~~~~~~~~~~~~~~~
Sometimes it may be useful to give a handler more information about the function that was called,
like the parameters it was passed. If you define your handler to take one or more specially-named
args, they will be automatically injected for you. These currently include::

funcargs
    The list of all `cffi`-level args (including output args) that were passed to the C function

niceobj
    The `NiceObject` instance whose method was called, or None for a top-level function


NiceObjects
-----------
Often a C library exposes a distinctly object-like interface like the one in our example.
Essentially, you have a handle or ID for some resource (a motor in our case), which gets passed as
the first argument to a subset of the library's functions. It makes sense to treat these as the
methods of some type of object. `NiceLib` allows you to define these types of objects via
`NiceObjectDef`.

A `NiceObjectDef` definition is mostly just a grouping of function signatures, with some optional
type-scoped settings (`prefix`, `ret`, and `buf_len`). The `NiceObjectDef` constructor also takes a
few more optional parameters, which we'll describe below. When your `NiceLib` subclass's definition
is processed by the metaclass, a sublass of `NiceObject` is created for each `NiceObjectDef` you
created. These `NiceObject` subclasses can then be instantiated and used to invoke methods.

So how does NiceLib attach a handle to each object instance? It uses the argument passed into the
`NiceObject`'s constructor. This gets stored with the object, and is automatically passed as the
first argument to all its wrapped C-functions, so you don't have to specify it all the time. It
looks something like this::

    handle = MyNiceLib.GetHandle()
    my_obj = MyNiceLib.MyObject(handle)
    my_obj.AwesomeMethod()

In a case like this, we can make object creation even nicer by using the `init` keyword in
`NiceObjectDef()`. `init` should be the name of a wrapped function which returns the handle to be
used for the new object instance. It may take whatever arguments it wants, and these are passed in
from the object's constructor. In our case, we don't need any arguments at all; if our specification
looks something like this::

    class MyNiceLib(NiceLib):
        ...
        GetHandle = ('out')

        MyObject = NiceObjectDef(init='GetHandle', attrs=dict(
            ...
        ))

we can then do this::

    my_obj = MyNiceLib.MyObject()
    my_obj.AwesomeMethod()

and bypass passing around handles at all.

To give your `NiceObject` subclass a docstring to describe what it is, you may pass this as the
`doc` keyword to `NiceObjectDef()`.


Multi-value handles
~~~~~~~~~~~~~~~~~~~
Usually an object will have only a single value as its handle, like an ID. In the unusual case that
you have functions which take more than one value which act as a collective 'handle', you should
specify this number as `n_handles` when calling `NiceObjectDef()`.


Auto-Generating Bindings
------------------------

If nicelib is able to parse your library's headers successfully, you can generate a convenient
binding skeleton using `generate_bindings()`.
