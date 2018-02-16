Creating Mid-Level Bindings
===========================

`NiceLib` is the base class that provides a nice interface for quickly defining mid-level library bindings. You define a subclass for each specific library (.dll/.so file) you wish to wrap. `NiceLib`'s metaclass then converts your specification into a wrapped library. You use this subclass directly, without instantiating it.

What Are Mid-Level Bindings?
----------------------------
It's worth discussing what we mean by "mid-level" bindings. Mid-level bindings have a one-to-one correspondence between low-level functions and mid-level functions. The difference is that each mid-level function has a more Pythonic interface that lets the user mostly or entirely avoid working with `cffi` directly. In other words, the overall structure of the library stays the same, but each individual function's interface may change.

These mid-level bindings can then be used to craft high-level bindings that might have a completely different structure than the underlying low-level library.

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

    from nicelib import load_lib, NiceLib, Sig, NiceObject, RetHandler, ret_ignore

    @RetHandler(num_retvals=0)
    def ret_errcode(retval):
        if retval != 0:
            raise MotorError(NiceMotor.GetErrorString(retval))

    class NiceMotor(NiceLib):
        _info_ = load_lib('awesomemotor', __package__)
        _ret_ = ret_errcode
        _prefix_ = 'General'

        GetDeviceList = Sig('arr', 'len=20')
        GetErrorString = Sig('in', 'buf', 'len', ret=ret_ignore)
        OpenMotor = Sig('in', 'out')

        class Motor(NiceObject):
            _init_ = 'OpenMotor'
            _prefix_ = 'Motor'

            Close = Sig('in')
            MoveTo = Sig('in', 'in')
            GetPosition = Sig('in', 'out')
            GetSerial = Sig('in', 'buf', 'len=64')

Then we can use the library like this::

    motor_ids = NiceMotor.GetDeviceList()

    for motor_id in motor_ids:
        motor = NiceMotor.Motor(motor_id)
        pos = motor.GetPosition()
        serial = motor.GetSerial()
        print("Motor {} is at position {}".format(serial, pos))
        motor.Close()

There are a number of features in use in this example: prefix removal, return value wrapping, array and string buffer output, and `NiceObjectDef`\s with custom initializers. These make use of settings, which you can read more about below.


.. _settings:

Settings
--------
Settings, also called flags, give you extra control over how a library is wrapped. Settings are scoped, meaning that you can specify them on a class-wide, NiceObject-wide, and per-function basis. For example:

1. **Class-level**:
    Give the NiceLib class an attribute with the setting name surrounded by single underscores::
    
      class MyLib(NiceLib):
          _buflen_ = 128

2. **NiceObject-level**: 
    Give the NiceObject class an attribute with the setting name surrounded by single underscores::

      class MyLib(NiceLib):
          class MyObject(NiceObject):
              _buflen_ = 128

3. **Function-level**:
    Pass settings as keyword args to the ``Sig`` constructor::

      MyFunction = Sig('in', 'in', 'out', buflen=128)


The available settings are:

prefix
    A ``str`` or sequence of ``str``\s specifying prefixes to strip from the library function names. For example, if the library has functions named like ``SDK_Func()``, you can set ``_prefix_`` to ``'SDK_'``, and access them as ``Func()``. If multiple prefixes are given, they are tried in order for each signature until the appropraite function is found. The empty prefix ``''`` is always tried. Sometimes you may want to specify one library-wide prefix and a different per-object prefix, as done in the above example.

    These prefixes also get stripped from macro names and enum constants.

ret
    A function or ``str`` specifying a handler function to handle the return values of each library function. See :ref:`retval-handlers` for details.

buflen
    An ``int`` specifying the default length for buffers and arrays. This can be overridden on a per-argument basis in the argument's spec string, e.g. ``'len=64'`` will make a 64-character buffer or a 64-element array.

free_buf
    A function that is called on the pointer returned for 'bufout' argtypes, used for freeing their associated memory. It is called immediately after the buffer is copied to produce a Python string, but is not called if a null pointer is returned. May be None.

use_numpy
    If True, convert output args marked as ``'arr'`` to numpy arrays. Requires numpy to be installed.

struct_maker
    A function that is called to create an FFI struct of the given type. Mainly useful for odd libraries that require you to always fill out some field of the struct, like its size in bytes.


``NiceLib`` Class Attributes
----------------------------
``NiceLib`` subclasses make use of a few underscore-surrounded special class attributes. In addition to the class-wide *settings* described above, they include:

_info_
    A `LibInfo` object that contains access to the underlying library and macros. Required (unless you are using the old-style ``_ffi_``, ``_ffilib_``, and ``_defs_`` attributes)

Typically you will want to pass the relevant library attributes via a `LibInfo` instance created using :py:func:`~nicelib.load_lib`, as shown in the examples above. However, it is currently possible to specify them directly. This was the original method, but may become deprecated in later versions of `NiceLib`.

_ffi_
    FFI instance variable. Required if not using ``_info_``.

_ffilib_
    FFI library opened with ``ffi.dlopen()``. Required if not using ``_info_``.

_defs_
    ``dict`` containing the Python-equivalent macros defined in the header file(s). Optional and only used if not using ``_info_``.


Function Signatures
-------------------

Function signatures are specified as ``Sig`` class attributes. A ``Sig``\s positional args are strings that define the input-output signature of the underlying C function. Per-function settings, like custom return value handling, are passed as keyword args.

It's important to note that a ``Sig`` is designed to closely match the signature of its C function, i.e. there's a one-to-one correspondence between arg strings and C function args.

The basic idea behind signature specifications is to handle input and output in a more Pythonic manner---inputs get passed in via a function's arguments, while its outputs get returned as part of the function's return values. Take the simple example from above::

    OpenMotor = Sig('in', 'out')

This says that the C function's first argument (``uint motorID``) is used strictly as input, and its second argument (``HANDLE *phMotor``) is used strictly as output---the function takes an ID number and returns a handle to a newly opened motor. Using this signature allows us to call the function more naturally as ``handle = OpenMotor(motorID)``.

The available signature values are:

'in'
    The argument is an input and gets passed into the mid-level function.

'out'
    The argument is an output. It is not passed into the mid-level function, but is instead added to the list of return values. NiceLib automatically allocates an appropriate data structure, passes its address-pointer to the C function, uses the dereferenced result as the return value.

    This can't be used for ``void`` pointers, since there's no way to know what to allocate, or what type to return.

'inout'
    The argument is used as both input and output. The mid-level function takes it as an argument and also returns it with the return values. You can pass in either a value or a pointer to the value. For example, if the underlying C argument is an ``int *``, you can pass in a ``cffi`` ``int`` pointer, which will be used directly, or (more typically) you can pass in a Python int, which will be used as the initial value of a newly-created ``cffi`` int pointer.

'bufout'
    The argument is a pointer to a string buffer (a ``char**``). This is used for when the C library creates a string buffer and returns it to the user. NiceLib will automatically convert the output to a Python ``bytes``, or None if a null pointer was returned.

    If the memory should be cleaned up by the user (as is usually the case), you may use the ``free_buf`` setting to specify the cleanup function.

'buf'
    The argument is a string buffer used for output. The C argument is a ``char`` pointer or array, into which the C-function writes a null-terminated string. This string is decoded using ``ffi.string()``, and added to the return values.

    This is used for the common case of a C function which takes both a string buffer and its length as inputs, so that it doesn't overrun the buffer. As such, ``'buf'`` requires a corresponding ``'len'`` entry. The first ``'buf'``/``'arr'`` is matched with the first ``'len'`` and so forth. If you don't need to pass in a length parameter to the C-function, use ``'buf[n]'`` as described below.

    NiceLib will automatically create the buffer and pass it and the length parameter to the C-function. You simply receive the ``bytes``.

'buf[n]'
    The same as ``'buf'``, but does not have a matching ``'len'``. Because of this, the buffer length is specified directly as an int. For example, a 20-char buffer would be ``'buf[20]'``.

'arr'
    The same as ``'buf'``, but does not call ``ffi.string()`` on the returned value. Used e.g. for ``int`` arrays.

'arr[n]'
    The same as ``'buf[n]'``, but does not call ``ffi.string()`` on the returned value. Used e.g. for ``int`` arrays.

'len'
    The length of the buffer being passed to the C-function. See ``'buf'`` for more info. This will use the length given by the innermost ``buflen`` setting.
    
'len=n'
    The same as ``'len'``, but with an overridden length. For example, ``'len=32'`` would allocate a buffer or array of length 32, regardless of what ``buflen`` is.

'len=in'
    Similar to ``'len=n'``, except the mid-level function takes an input argument which is an ``int`` specifying the size of buffer that should be allocated for that invocation.

'ignore'
    Ignore the argument, passing in 0 or NULL, depending on the arg type. This is useful for functions with "reserved" arguments which don't do anything.


.. _retval-handlers:

Return Value Handlers
---------------------
``RetHandler``\s, which specify functions to handle the return values of each library function, are given via the ``ret`` flag, as mentioned in :ref:`settings`. Return handlers are created by using the ``@RetHandler`` decorator---for example, the built-in ``ret_return`` handler is defined thusly::

    @RetHandler(num_retvals=1)
    def ret_return(retval):
        return retval

``num_retvals`` indicates the number of values that the handler returns, which is often zero. Return handlers can be used to raise exceptions, return values, or even do custom handling based on what args were passed to the function.

A handler function takes the C function's return value---often an error/success code---as its first argument (see below for other optional parameters it may take). If the handler returns a non-None value, it will be appended to the wrapped function's return values.


Builtin Handlers
~~~~~~~~~~~~~~~~
There are two handlers that nicelib defines for convenience:

`ret_return()`
    The default handler. Simply appends the return value to the wrapped function's return values.

`ret_ignore()`
    Ignores the value entirely and does not return it. Useful for ``void`` functions


Injected Parameters
~~~~~~~~~~~~~~~~~~~
Sometimes it may be useful to give a handler more information about the function that was called, like the C parameters it was passed. If you define your handler to take one or more specially-named args, they will be automatically injected for you. These include::

funcargs
    The list of all ``cffi``\-level args (including output args) that were passed to the C function

niceobj
    The `NiceObject` instance whose method was called, or None for a top-level function


NiceObjects
-----------
Often a C library exposes a distinctly object-like interface like the one in our example. Essentially, you have a handle or ID of some resource (a motor in the example), which gets passed as the first argument to a subset of the library's functions. It makes sense to treat these functions as the *methods* of some type of object. NiceLib allows you to define these types of objects by subclassing `NiceObject`.

`NiceObject` class definitions are nested inside your `NiceLib` class definition, and consist of method ``Sig``\s and object-specific settings. When you instantiate a `NiceObject`, the args are passed to the `NiceObject`\'s *initializer*, which returns a handle. This handle is passed as the first parameter to all of the `NiceObject`\'s "methods". This initializer is specified using the `NiceObject`\'s ``_init_`` class attribute, which can be either a function or the name of one of the mid-level functions (as with ``'OpenMotor'`` in the example above). If ``_init_`` is not defined, the args passed to the `NiceObject`\'s constructor are used directly as the handle.

Without using ``_init_``, object construction would look like this::

    handle = MyNiceLib.GetHandle()
    my_obj = MyNiceLib.MyObject(handle)
    my_obj.AwesomeMethod()

But if we use ``_init_``::

    class MyNiceLib(NiceLib):
        [...]
        GetHandle = ('out')

        class MyObject(NiceObject):
            _init_ = 'GetHandle'
            [...]

we can then do this::

    my_obj = MyNiceLib.MyObject()
    my_obj.AwesomeMethod()

and bypass passing around handles at all.


Multi-value handles
~~~~~~~~~~~~~~~~~~~
Usually an object will have only a single value as its handle, like an ID. In the unusual case that you have functions which take more than one value which act as a collective 'handle', you should specify this number as ``_n_handles_`` in your `NiceObject` subclass.


Auto-Generating Bindings
------------------------
If nicelib is able to parse your library's headers successfully, you can generate a convenient binding skeleton using `generate_bindings()`.
