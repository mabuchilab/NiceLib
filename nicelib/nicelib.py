# -*- coding: utf-8 -*-
# Copyright 2015-2016 Nate Bogdanowicz
from builtins import str, zip, object
from past.builtins import basestring
from future.utils import with_metaclass

import sys
import warnings
from inspect import isfunction


def _wrap_ndarrays(ffi, argtype, arg):
    import numpy as np
    if isinstance(arg, np.ndarray):
        if argtype.kind != 'pointer':
            raise TypeError
        elif argtype.item.kind != 'primitive':
            raise TypeError

        cname = argtype.item.cname
        if cname.startswith('int'):
            prefix = 'i'
        elif cname.startswith('uint'):
            prefix = 'u'
        elif cname.startswith(('float', 'double')):
            prefix = 'f'
        else:
            raise TypeError("Unknown type {}".format(cname))

        dtype = np.dtype(prefix + str(ffi.sizeof(argtype.item)))

        if arg.dtype != dtype:
            raise TypeError

        return ffi.cast(argtype, arg.ctypes.data)
    else:
        return arg


def _cffi_wrapper(ffi, func, fname, sig_tup, err_wrap, struct_maker, default_buflen):
    argtypes = ffi.typeof(func).args
    n_expected_inargs = sum('in' in a for a in sig_tup)

    if len(sig_tup) != len(argtypes):
        raise TypeError("{}() takes {} args, but your signature specifies "
                        "{}".format(fname, len(argtypes), len(sig_tup)))

    def wrapped(*inargs):
        inargs = list(inargs)

        if len(inargs) != n_expected_inargs:
            message = '{}() takes '.format(fname)
            if n_expected_inargs == 0:
                message += 'no arguments'
            elif n_expected_inargs == 1:
                message += '1 argument'
            else:
                message += '{} arguments'.format(n_expected_inargs)

            message += ' ({} given)'.format(len(inargs))

            raise TypeError(message)

        # First pass to get buf/arr info
        buflens, lens, solo_buflens = [], [], []
        n_paired_bufs = 0
        inarg_idx = 0
        for sig, argtype in zip(sig_tup, argtypes):
            if sig.startswith(('buf', 'arr')):
                if len(sig) > 3:
                    try:
                        assert sig[3] == '[' and sig[-1] == ']'
                        num = int(sig[4:-1])
                        assert num > 0
                    except (AssertionError, ValueError):
                        raise ValueError("Bad sig element '{}'".format(sig))
                    solo_buflens.append(num)
                else:
                    n_paired_bufs += 1

            elif sig.startswith('len'):
                if len(sig) == 3:
                    num = default_buflen
                else:
                    try:
                        assert sig[3] == '='
                        if sig[4:] == 'in':
                            num = inargs[inarg_idx]
                        else:
                            num = int(sig[4:])
                    except (AssertionError, ValueError):
                        raise ValueError("Bad sig element '{}'".format(sig))
                lens.append(num)
                buflens.append(num)

            if 'in' in sig:
                inarg_idx += 1

        if len(lens) != n_paired_bufs:
            raise ValueError("Number of paired buf/arr sig elements does not match number of "
                             "len sig elements")

        outargs = []
        args = []
        bufs = []
        # Possible sig entries:
        # - in
        # - out
        # - inout
        # - buf[n]  (c-string buffer)
        # - arr[n]  (array)
        # - len=n   (length of buf/arr)
        # - retlen??(returned length)
        # - ignore  (reserved arg, pass in 0/NULL)
        for info, argtype in zip(sig_tup, argtypes):
            if info == 'inout':
                inarg = inargs.pop(0)
                try:
                    inarg_type = ffi.typeof(inarg)
                except TypeError:
                    inarg_type = type(inarg)

                if argtype == inarg_type:
                    arg = inarg  # Pass straight through
                elif argtype.kind == 'pointer' and argtype.item.kind == 'struct':
                    arg = struct_maker(argtype, inarg)
                else:
                    arg = ffi.new(argtype, inarg)
                outargs.append((arg, lambda o: o[0]))
            elif info == 'in':
                arg = inargs.pop(0)
                arg = _wrap_ndarrays(ffi, argtype, arg)
            elif info == 'out':
                if argtype.kind == 'pointer' and argtype.item.kind == 'struct':
                    arg = struct_maker(argtype)
                else:
                    arg = ffi.new(argtype)
                outargs.append((arg, lambda o: o[0]))
            elif info.startswith('buf'):
                buflen = (buflens if len(info) == 3 else solo_buflens).pop(0)
                arg = ffi.new('char[]', buflen)
                outargs.append((arg, lambda o: ffi.string(o)))
                bufs.append(arg)
            elif info.startswith('arr'):
                buflen = (buflens if len(info) == 3 else solo_buflens).pop(0)
                arg = ffi.new('{}[]'.format(argtype.item.cname), buflen)
                outargs.append((arg, lambda o: o))
                bufs.append(arg)
            elif info.startswith('len'):
                if info == 'len=in':
                    inargs.pop(0)  # We've already used this earlier
                arg = lens.pop(0)
            elif info == 'ignore':
                arg = ffi.new(argtype.cname + '*')[0]
            else:
                raise Exception("Unrecognized arg info '{}'".format(info))

            if isinstance(arg, str):
                arg = arg.encode('ascii')
            args.append(arg)

        retval = func(*args)
        out_vals = [f(a) for a, f in outargs]

        if err_wrap:
            err_wrap(retval)
        else:
            out_vals.append(retval)

        if not out_vals:
            return None
        elif len(out_vals) == 1:
            return out_vals[0]
        else:
            return tuple(out_vals)

    wrapped.__name__ = fname
    wrapped._ffi_func = func
    wrapped._sig_tup = sig_tup
    return wrapped


# WARNING uses some stack frame hackery; should probably make use of this syntax optional
class NiceObject(object):
    def __init__(self, attrs=None, n_handles=1):
        self.attrs = attrs
        self.n_handles = n_handles
        self.doc = None

        if attrs is not None:
            self.names = set(attrs.keys())

    def __enter__(self):
        if self.attrs is not None:
            raise Exception("NiceObject already constructed with an `attrs` dict, this is not "
                            "compatible with the context manager syntax")
        outer_vars = sys._getframe(1).f_locals
        self.doc = outer_vars.pop('__doc__', None)
        self._enter_names = set(outer_vars.keys())  # Not including __doc__
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        outer_vars = sys._getframe(1).f_locals
        new_doc = outer_vars.pop('__doc__', None)

        exit_names = set(outer_vars.keys())
        self.names = exit_names.difference(self._enter_names)

        if new_doc:
            outer_vars['__doc__'] = self.doc  # Put old var back
        self.doc = new_doc

    def __str__(self):
        return str(self.names)

    def __repr__(self):
        return repr(self.names)


class LibMeta(type):
    def __new__(metacls, clsname, bases, classdict):
        mro_lookup = metacls._create_mro_lookup(classdict, bases)

        ffi = classdict['_ffi']
        lib = classdict['_lib']
        defs = mro_lookup('_defs')
        prefixes = mro_lookup('_prefix')
        err_wrap = mro_lookup('_err_wrap')
        struct_maker = mro_lookup('_struct_maker') or (ffi.new if ffi else None)
        buflen = mro_lookup('_buflen')

        # Add default empty prefix
        if isinstance(prefixes, basestring):
            prefixes = (prefixes, '')
        else:
            prefixes = tuple(prefixes) + ('',)

        niceobjects = {}  # name: NiceObject
        for name, value in list(classdict.items()):
            if isinstance(value, NiceObject):
                if value.attrs is None:
                    value.names.remove(name)  # Remove self
                else:
                    for attr_name, attr_val in value.attrs.items():
                        classdict[attr_name] = attr_val
                niceobjects[name] = value

        funcs = {}

        for name, value in classdict.items():
            if (not name.startswith('_') and not isinstance(value, NiceObject)):
                if isfunction(value):
                    func = value
                    repr_str = func.__doc__ or "{}(??) -> ??".format(name)
                else:
                    sig_tup = value
                    flags = {}

                    if not isinstance(sig_tup, tuple):
                        sig_tup = (sig_tup,)

                    # Pop off the flags dict
                    if sig_tup and isinstance(sig_tup[-1], dict):
                        flags.update(sig_tup[-1])
                        sig_tup = sig_tup[:-1]

                    # Try prefixes until we find the lib function
                    for prefix in prefixes:
                        ffi_func = getattr(lib, prefix + name, None)
                        if ffi_func is not None:
                            break

                    if ffi_func is None:
                        raise AttributeError("No lib function found with a name ending in '{}', wi"
                                             "th any of these prefixes: {}".format(name, prefixes))

                    func = _cffi_wrapper(ffi, ffi_func, name, sig_tup, err_wrap, struct_maker,
                                         buflen)
                    repr_str = metacls._func_repr_str(ffi, func)

                # Save for use by niceobjs
                funcs[name] = func

                # HACK to get nice repr
                classdict[name] = LibFunction(func, repr_str)

        for cls_name, niceobj in niceobjects.items():
            # Need to use a separate function so we have a per-class closure
            classdict[cls_name] = metacls._create_object_class(cls_name, niceobj, ffi, funcs)

        # Add macro defs
        if defs:
            for name, attr in defs.__dict__.items():
                for prefix in prefixes:
                    if name.startswith(prefix):
                        shortname = name[len(prefix):]
                        if shortname in classdict:
                            warnings.warn("Conflicting name {}, ignoring".format(shortname))
                        else:
                            classdict[shortname] = staticmethod(attr) if callable(attr) else attr
                        break

        return super(LibMeta, metacls).__new__(metacls, clsname, bases, classdict)

    @classmethod
    def _create_object_class(metacls, cls_name, niceobj, ffi, funcs):
        repr_strs = {}
        for func_name in niceobj.names:
            func = funcs[func_name]
            if hasattr(func, '_ffi_func'):
                repr_str = metacls._func_repr_str(ffi, funcs[func_name], niceobj.n_handles)
            else:
                repr_str = func.__doc__ or '{}(??) -> ??'.format(func_name)
            repr_strs[func_name] = repr_str

        def __init__(self, *handles):
            if len(handles) != niceobj.n_handles:
                raise TypeError("__init__() takes exactly {} arguments "
                                "({} given)".format(niceobj.n_handles, len(handles)))

            # Generate "bound methods"
            for func_name in niceobj.names:
                lib_func = LibFunction(funcs[func_name], repr_strs[func_name], handles)
                setattr(self, func_name, lib_func)

        niceobj_dict = {'__init__': __init__, '__doc__': niceobj.doc}
        return type(cls_name, (object,), niceobj_dict)

    @staticmethod
    def _create_mro_lookup(classdict, bases):
        """Generate a lookup function that will search the base classes for an attribute. This
        only searches the mro of the first base, which is OK since you should probably inherit only
        from NiceLib anyway. If there's a use case where multiple inheritance becomes useful, we
        can add the proper mro algorithm here, but that seems unlikely. In fact, even this seems
        like overkill...
        """
        dicts = (classdict,) + tuple(C.__dict__ for C in bases[0].__mro__)
        def lookup(name):
            for d in dicts:
                try:
                    return d[name]
                except KeyError:
                    pass
            raise KeyError(name)
        return lookup

    @staticmethod
    def _func_repr_str(ffi, func, n_handles=0):
        argtypes = ffi.typeof(func._ffi_func).args

        if n_handles > len(func._sig_tup):
            raise ValueError("Signature for function '{}' is missing its required "
                             "handle args".format(func.__name__))

        in_args = [a.cname for a, d in zip(argtypes, func._sig_tup) if 'in' in d][n_handles:]
        out_args = [a.item.cname for a, d in zip(argtypes, func._sig_tup)
                    if d.startswith(('out', 'buf', 'arr'))]

        if not out_args:
            out_args = ['None']

        repr_str = "{}({}) -> {}".format(func.__name__, ', '.join(in_args), ', '.join(out_args))
        return repr_str


class LibFunction(object):
    def __init__(self, func, repr_str, handles=()):
        self.__name__ = func.__name__
        self._func = func
        self._repr = repr_str
        self._handles = handles

    def __call__(self, *args):
        return self._func(*(self._handles + args))

    def __str__(self):
        return self._repr

    def __repr__(self):
        return self._repr


class NiceLib(with_metaclass(LibMeta, object)):
    """Base class for mid-level library wrappers

    Provides a nice interface for quickly defining mid-level library wrappers. You define a
    subclass for each specific library (DLL).

    Attributes
    ----------
    _ffi
        FFI instance variable. Required.
    _lib
        FFI library opened with `dlopen()`. Required.
    _ defs
        Object whose attributes are the Python-equivalent macros defined in the header file(s).
        Optional.
    _prefix : str or sequence of strs, optional
        Prefix(es) to strip from the library function names. E.g. If the library has functions
        named like ``SDK_Func()``, you can set `_prefix` to ``'SDK_'``, and access them as
        `Func()`. If more than one prefix is given, they are tried in order for each signature
        until the appropraite function is found.
    _err_wrap : function, optional
        Wrapper function to handle error codes returned by each library function.
    _struct_maker : function, optional
        Function that is called to create an FFI struct of the given type. Mainly useful for
        odd libraries that require you to always fill out some field of the struct, like its size
        in bytes
    _buflen : int, optional
        The default length for buffers. This can be overridden on a per-argument basis in the
        argument's spec string, e.g `'len=64'` will make a 64-byte buffer.
    """
    _ffi = None  # MUST be filled in by subclass
    _lib = None  # MUST be filled in by subclass
    _defs = None
    _prefix = ''
    _struct_maker = None  # ffi.new
    _buflen = 512

    def _err_wrap(ret_code):
        pass

    def __new__(cls):
        raise Exception("Not allowed to instantiate {}".format(cls))
