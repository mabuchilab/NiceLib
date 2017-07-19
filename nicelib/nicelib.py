# -*- coding: utf-8 -*-
# Copyright 2015-2017 Nate Bogdanowicz
from __future__ import division, absolute_import, with_statement, print_function, unicode_literals

from builtins import str, zip
from past.builtins import basestring
from future.utils import with_metaclass

import sys
import warnings
import pickle as pkl
import logging as log
from inspect import isfunction, getargspec

import cffi

from . import test_mode_is, _test_mode
from .util import to_tuple

__all__ = ['NiceLib', 'NiceObjectDef']
FLAGS = ('prefix', 'ret', 'struct_maker', 'buflen', 'use_numpy', 'free_buf')


class StateNode(object):
    def __init__(self, result=None):
        self.result = result
        self.children = {}
        self.attrs = {}

    def add_attr_access(self, name, value):
        self.attrs[name] = value

    def show(self, buf=sys.stdout, indent=0):
        prefix = ' ' * indent
        print(prefix + repr(self.attrs))

        for args, node in self.children.items():
            print(prefix + str(args[0]) + str(args[1:]))
            node.show(buf, indent + 2)

    def has_func(self, name):
        for args in self.children:
            if args[0] == name:
                return True
        return False


class Record(object):
    record = None
    rec_fpath = None

    def __init__(self):
        if self.record:
            raise Exception("record already exists")

        self.__class__.record = self
        self.root = StateNode()
        self.cur_state = self.root
        self.niceobjs = {}

    def add_niceobject(self, cls_name, handles):
        handles = tuple(self.encode_arg(h) for h in handles)
        obj = MockNiceObject(cls_name, handles)

    def get_attr(self, name):
        if name in self.cur_state.attrs:
            return self.cur_state.attrs[name]
        elif self.cur_state.has_func(name):
            return LibFunction(None, '', )
        elif name in self.niceobjs:
            return self.niceobjs[name]

        self.cur_state.show()
        raise AttributeError(name)

    def get_niceobj_attr(self, name):
        pass

    def reset(self):
        self.cur_state = self.root

    def add_func_call(self, func_name, handles, args, result):
        new_state = StateNode(result)

        handles = self.encode_args(handles)
        args = self.encode_args(args)
        key = ('func', func_name, handles, args)

        self.cur_state.children[key] = new_state
        self.cur_state = new_state

        if '.' in func_name:
            obj_name = func_name.split('.')[0]
            #classdict = {}
            #obj_class = type(obj_name, (object,), classdict)
            self.niceobjs[obj_name] = MockNiceObjectClass(obj_name)

    def add_attr_access(self, name, value):
        self.cur_state.add_attr_access(name, value)

    @staticmethod
    def encode_args(args):
        return tuple(Record.encode_arg(arg) for arg in args)

    @staticmethod
    def encode_arg(arg):
        if 'CData' in str(type(arg)):
            return MockCData(arg)
        else:
            return arg

    def show(self):
        print('Record:')
        self.root.show(indent=2)

    @classmethod
    def load(cls):
        if cls.rec_fpath is None:
            raise ValueError("Record.rec_fpath not set, can't load record file!")

        with open(cls.rec_fpath, 'rb') as f:
            cls.record = pkl.load(f)

    def save(self, fname):
        with open(fname, 'wb') as f:
            pkl.dump(self, f)

    @classmethod
    def ensure_created(cls):
        if cls.record is None:
            if test_mode_is('replay'):
                Record.load()
            elif test_mode_is('record', 'run'):
                print("Creating new record")
                cls.record = cls()
            else:
                raise Exception("Unknown mode '{}'".format(_test_mode.mode))


class NiceObject(object):
    pass


class NiceClassMeta(type):
    def __new__(metacls, cls_name, niceobjdef, ffi, funcs, user_funcs):
        repr_strs = {}
        for func_name in niceobjdef.names:
            if func_name in funcs:
                func = funcs[func_name]
                if hasattr(func, '_ffi_func'):
                    repr_str = _func_repr_str(ffi, funcs[func_name], niceobjdef.n_handles)
                else:
                    repr_str = func.__doc__ or '{}(??) -> ??'.format(func_name)
                repr_strs[func_name] = repr_str

        # Get init function
        try:
            init_func = funcs[niceobjdef.init] if niceobjdef.init else None
        except KeyError:
            raise ValueError("Could not find function '{}'".format(niceobjdef.init))

        def __init__(self, *args):
            handles = init_func(*args) if init_func else args
            if not isinstance(handles, tuple):
                handles = (handles,)
            self._handles = handles

            if len(handles) != niceobjdef.n_handles:
                raise TypeError("__init__() takes exactly {} arguments "
                                "({} given)".format(niceobjdef.n_handles, len(handles)))

            # Generate "bound methods"
            for func_name in niceobjdef.names:
                if func_name in funcs:
                    lib_func = LibFunction(funcs[func_name], repr_strs[func_name], handles,
                                           cls_name, self)
                    if func_name in user_funcs:
                        wrapped_func = user_funcs[func_name]
                        wrapped_func.orig = lib_func
                        setattr(self, func_name, wrapped_func)
                    else:
                        setattr(self, func_name, lib_func)

            if test_mode_is('record'):
                Record.ensure_created()
                Record.record.add_niceobject(cls_name, handles)

        niceobj_dict = {'__init__': __init__, '__doc__': niceobjdef.doc}
        return type(cls_name, (NiceObject,), niceobj_dict)


class MockNiceObjectClass(object):
    def __init__(self, name):
        self.name = name

    def __call__(self, *args, **kwds):
        return MockNiceObject(self.name)


class MockNiceObject(object):
    def __init__(self, clsname, handles):
        self.clsname = clsname
        self.handles = handles

    def __getattr__(self, name):
        if test_mode_is('replay'):
            if not name.startswith('__'):
                print("Getting '{}'".format(name))
                Record.ensure_created()
                return Record.record.get_niceobj_attr('{}.{}'.format(self.clsname, name))
        raise AttributeError(name)


class MockCData(object):
    def __init__(self, cdata):
        self.str = str(cdata)

    def __repr__(self):
        return self.str


def _wrap_inarg(ffi, argtype, arg):
    """Convert an input arg to the argtype required by the underlying C function

    `argtype` is the ffi.CType to which `arg` should be converted.

    Converts a string to `char *` or `char[]`
    Converts a number to its corresponding CType
                      or a new pointer to the number
    Converts a numpy array to the correct numeric pointer (only flat arrays for now)
    Creates a pointer to arg if argtype is a typeof(arg) pointer
    Otherwise, tries to cast arg to argtype via ffi.cast()

    If `argtype` is not a CType, returns `arg` unmodified
    """
    # For variadic args, we can't rely on cffi auto-converting our arg to the right cdata type, so
    # we do it ourselves instead
    try:
        import numpy as np
        HAS_NUMPY = True
    except ImportError:
        HAS_NUMPY = False

    if HAS_NUMPY and isinstance(arg, np.ndarray):
        if argtype.kind != 'pointer':
            raise TypeError
        elif argtype.item.kind != 'primitive':
            raise TypeError

        cname = argtype.item.cname
        if cname.startswith(('int', 'long', 'short', 'char', 'signed')):
            prefix = 'i'
        elif cname.startswith('unsigned'):
            prefix = 'u'
        elif cname.startswith(('float', 'double')):
            prefix = 'f'
        else:
            raise TypeError("Unknown type {}".format(cname))

        dtype = np.dtype(prefix + str(ffi.sizeof(argtype.item)))

        if arg.dtype != dtype:
            raise TypeError

        return ffi.cast(argtype, arg.ctypes.data)

    elif isinstance(argtype, ffi.CType):
        # Convert strings
        if argtype.cname in ('char *', 'char[]') and isinstance(arg, (str, bytes)):
            if isinstance(arg, str):
                arg = arg.encode()
            return ffi.new('char[]', arg)

        else:
            try:
                return ffi.new(argtype, arg)
            except TypeError:
                pass

            try:
                return ffi.cast(argtype, arg)
            except TypeError:
                pass

        raise TypeError("A value castable to (or a valid initializer for) '{}' is required, "
                        "got '{}'".format(argtype, arg))
    else:
        return arg


def _cffi_wrapper(ffi, func, fname, sig_tup, prefix, ret, struct_maker, buflen,
                  use_numpy, free_buf):
    default_buflen = buflen
    ret_handler_args = set(getargspec(ret).args[1:])

    def bufout_wrap(buf_ptr):
        """buf_ptr is a char**"""
        if buf_ptr[0] == ffi.NULL:
            return None

        string = ffi.string(buf_ptr[0])
        if free_buf:
            free_buf(buf_ptr[0])
        return string

    def c_to_numpy_array(c_arr, size):
        import numpy as np
        arrtype = ffi.typeof(c_arr)
        cname = arrtype.item.cname
        if cname.startswith(('int', 'long', 'short', 'char', 'signed')):
            prefix = 'i'
        elif cname.startswith('unsigned'):
            prefix = 'u'
        elif cname.startswith(('float', 'double')):
            prefix = 'f'
        else:
            raise TypeError("Unknown type {}".format(cname))

        dtype = np.dtype(prefix + str(ffi.sizeof(arrtype.item)))
        return np.frombuffer(ffi.buffer(c_arr), dtype=dtype)

    arr_out_wrapper = c_to_numpy_array if use_numpy else (lambda arr, size: arr)

    functype = ffi.typeof(func)
    argtypes = functype.args
    # Cast bytes to str
    sig_tup = tuple(str(sig) if isinstance(sig, bytes) else sig for sig in sig_tup)
    n_expected_inargs = sum('in' in a for a in sig_tup if isinstance(a, str))

    if functype.ellipsis:
        argtypes = argtypes + ('...',)

    if len(sig_tup) != len(argtypes):
        raise TypeError("{}() takes {} args, but your signature specifies "
                        "{}".format(fname, len(argtypes), len(sig_tup)))

    def wrapped(*inargs, **kwds):
        inargs = list(inargs)
        available_args = {}
        available_args['niceobj'] = kwds.pop('niceobj', None)
        available_args['funcname'] = fname

        if not functype.ellipsis and len(inargs) != n_expected_inargs:
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
        buflens, lens, solo_buflens, buftypes = [], [], [], []
        n_paired_bufs = 0
        inarg_idx = 0
        for sig, argtype in zip(sig_tup, argtypes):
            if argtype == '...':
                continue

            elif sig in ('buf', 'arr'):
                n_paired_bufs += 1
                buftypes.append(argtype.item)

            elif sig.startswith(('buf[', 'arr[')):
                try:
                    assert sig[3] == '[' and sig[-1] == ']'
                    num = int(sig[4:-1])
                    assert num > 0
                except (AssertionError, ValueError):
                    raise ValueError("Bad sig element '{}'".format(sig))
                solo_buflens.append(num)

            elif sig.startswith('len'):
                sig, _, size_type = sig.partition(':')

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
            if argtype == '...':
                info, argtype = info(*args)

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
                    try:
                        arg = ffi.new(argtype, inarg)
                    except TypeError:
                        raise TypeError("Cannot convert {} to required type"
                                        "{}".format(inarg, argtype))

                if argtype.kind == 'pointer' and argtype.item.cname == 'void':
                    # Don't dereference void pointers directly
                    outargs.append((arg, lambda o: o))
                else:
                    outargs.append((arg, lambda o: o[0]))
            elif info == 'in':
                arg = inargs.pop(0)
                arg = _wrap_inarg(ffi, argtype, arg)
            elif info == 'out':
                if argtype.kind == 'pointer' and argtype.item.kind == 'struct':
                    arg = struct_maker(argtype)
                else:
                    arg = ffi.new(argtype)
                outargs.append((arg, lambda o: o[0]))
            elif info == 'bufout':
                if not (argtype.kind == 'pointer' and argtype.item.kind == 'pointer' and
                        argtype.item.item.kind == 'primitive'):
                    raise TypeError("'bufout' applies only to type 'char**'")
                arg = ffi.new(argtype)
                outargs.append((arg, bufout_wrap))
            elif info.startswith('buf'):
                buflen = (buflens if len(info) == 3 else solo_buflens).pop(0)
                arg = ffi.new('char[]', buflen)
                outargs.append((arg, lambda o: ffi.string(o)))
                bufs.append(arg)
            elif info.startswith('arr'):
                buflen = (buflens if len(info) == 3 else solo_buflens).pop(0)
                arg = ffi.new('{}[]'.format(argtype.item.cname), buflen)
                outargs.append((arg, lambda arr: arr_out_wrapper(arr, buflen)))
                bufs.append(arg)
            elif info.startswith('len'):
                info, _, size_type = info.partition(':')
                if info == 'len=in':
                    inargs.pop(0)  # We've already used this earlier
                buftype = buftypes.pop(0)

                # Adjust len if sig has an explicit type
                if not size_type:
                    meas_size = ffi.sizeof(buftype)
                elif size_type == 'byte':
                    meas_size = 1
                else:
                    meas_size = ffi.sizeof(size_type)

                arg = lens.pop(0) * ffi.sizeof(buftype) // meas_size
            elif info == 'ignore':
                arg = ffi.new(argtype.cname + '*')[0]
            else:
                raise Exception("Unrecognized arg info '{}'".format(info))

            if isinstance(arg, str):
                arg = arg.encode('ascii')
            args.append(arg)

        available_args['funcargs'] = args

        retval = func(*args)
        out_vals = [f(a) for a, f in outargs]

        if ret:
            try:
                kwds = {arg: available_args[arg] for arg in ret_handler_args}
            except KeyError as e:
                raise KeyError("Unknown arg '{}' in arglist of ret-handling function "
                               "'{}'".format(e.args[0], ret.__name__))
            retval = ret(retval, **kwds)

        if retval is not None:
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
class NiceObjectDef(object):
    def __init__(self, attrs=None, n_handles=1, init=None, doc=None, **flags):
        self.doc = doc
        self.attrs = attrs
        self.n_handles = n_handles

        if not (init is None or isinstance(init, basestring)):
            raise TypeError("NiceObjectDef's `init` arg must be a string that names a wrapped "
                            "function. Got '{}' instead.".format(type(init).__name__))
        self.init = init

        if attrs is not None:
            self.names = set(attrs.keys())

        if 'ret_wrap' in flags:
            warnings.warn("The 'ret_wrap' flag has been renamed to 'ret', please update your code")
            flags['ret'] = flags.pop('ret_wrap')

        bad_kwds = [k for k in flags if k not in FLAGS]
        if bad_kwds:
            raise ValueError("Unknown flags {}".format(bad_kwds))
        self.flags = flags

    def set_signatures(self, sigs={}, **kwds):
        self.attrs = sigs
        self.attrs.update(kwds)
        self.names = set(self.attrs.keys())

    def __enter__(self):
        if self.attrs is not None:
            raise Exception("NiceObjectDef already constructed with an `attrs` dict, this is not "
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


_contingent_libs = []


class LibMeta(type):
    def __new__(metacls, clsname, bases, classdict):
        if test_mode_is('replay'):
            return metacls.__new_replay__(clsname, bases, classdict)
        mro_lookup = metacls._create_mro_lookup(classdict, bases)

        # Deprecation warnings
        if '_err_wrap' in classdict:
            classdict['_ret'] = classdict.pop('_err_wrap')
            warnings.warn("Your class defines _err_wrap, which has been renamed to _ret, "
                          "please update your code")

        if '_ret_wrap' in classdict:
            classdict['_ret'] = classdict.pop('_ret_wrap')
            warnings.warn("Your class defines _ret_wrap, which has been renamed to _ret, "
                          "please update your code")

        if '_info' in classdict:
            info = classdict['_info']
            classdict['_ffi'] = info._ffi
            classdict['_ffilib'] = info._ffilib
            classdict['_defs'] = info._defs

        ffi = classdict['_ffi']
        lib = classdict['_ffilib']
        defs = mro_lookup('_defs')

        base_flags = {name: mro_lookup('_' + name) for name in FLAGS}
        if ffi and not base_flags['struct_maker']:
            base_flags['struct_maker'] = ffi.new

        dir_lib = []
        for name in dir(lib):
            try:
                attr = getattr(lib, name)
                if ffi and isinstance(attr, ffi.CData) and ffi.typeof(attr).kind != 'function':
                    dir_lib.append(name)
            except (AttributeError, cffi.FFIError):
                pass  # Name may be from a separate library's header

        # Add default empty prefix
        base_flags['prefix'] = to_tuple(base_flags['prefix'])
        if '' not in base_flags['prefix']:
            base_flags['prefix'] += ('',)

        # Unpack NiceObjectDef sigs into the classdict
        niceobjectdefs = {}  # name: NiceObjectDef
        func_to_niceobj = {}
        for name, value in list(classdict.items()):
            if isinstance(value, NiceObjectDef):
                niceobjdef = value
                if niceobjdef.attrs is None:
                    niceobjdef.names.remove(name)  # Remove self
                else:
                    for attr_name, attr_val in niceobjdef.attrs.items():
                        classdict[attr_name] = attr_val
                        func_to_niceobj[attr_name] = niceobjdef
                niceobjectdefs[name] = niceobjdef

        funcs = {}
        func_flags = {}
        user_funcs = {}
        ret_handlers = {
            'return': mro_lookup('_ret_return'),
            'ignore': mro_lookup('_ret_ignore')
        }

        for name, value in classdict.items():
            if name.startswith('_ret_') and isfunction(value):
                ret_handlers[name[5:]] = value

        for name, value in classdict.items():
            if (not name.startswith('_') and not isinstance(value, NiceObjectDef)):
                log.debug("Handling NiceLib attr '%s'", name)
                sig_tup = None
                if isfunction(value):
                    if hasattr(value, 'sig'):
                        sig_tup = value.sig
                        user_funcs[name] = value
                    else:
                        func = value
                        flags = {}
                        repr_str = func.__doc__ or "{}(??) -> ??".format(name)
                else:
                    sig_tup = value

                if sig_tup is not None:
                    flags = base_flags.copy()
                    if name in func_to_niceobj:
                        flags.update(func_to_niceobj[name].flags)

                    # Allow non-tuple, e.g. ('in') or ({'ret':'ignore'})
                    if not isinstance(sig_tup, tuple):
                        sig_tup = (sig_tup,)

                    # Pop off the flags dict
                    if sig_tup and isinstance(sig_tup[-1], dict):
                        func_flags = sig_tup[-1]

                        # Temporarily allow 'ret_wrap' for backwards compatibility
                        if 'ret_wrap' in func_flags:
                            warnings.warn("The 'ret_wrap' flag has been renamed to 'ret', please "
                                          "update your code")
                            func_flags['ret'] = func_flags.pop('ret_wrap')

                        flags.update(func_flags)
                        sig_tup = sig_tup[:-1]

                    flags['prefix'] = to_tuple(flags['prefix'])
                    if '' not in flags['prefix']:
                        flags['prefix'] += ('',)

                    # Try prefixes until we find the lib function
                    for prefix in flags['prefix']:
                        func_name = prefix + name
                        ffi_func = getattr(lib, func_name, None)
                        if ffi_func is not None:
                            break
                    else:
                        warnings.warn("No lib function found with a name ending in '{}', with "
                                      "any of these prefixes: {}".format(name, flags['prefix']))
                        continue

                    ret_handler = flags['ret']
                    if isinstance(ret_handler, basestring):
                        flags['ret'] = ret_handlers[flags['ret']]

                    func = _cffi_wrapper(ffi, ffi_func, name, sig_tup, **flags)
                    repr_str = _func_repr_str(ffi, func)

                # Save for use by niceobjs
                funcs[name] = func
                func_flags[name] = flags

                # HACK to get nice repr
                classdict[name] = LibFunction(func, repr_str)

        # Create NiceObject classes
        for cls_name, niceobjdef in niceobjectdefs.items():
            # Need to use a separate function so we have a per-class closure
            classdict[cls_name] = NiceClassMeta(cls_name, niceobjdef, ffi, funcs, user_funcs)

        # Add macro defs
        if defs:
            for name, attr in defs.items():
                for prefix in base_flags['prefix']:
                    if name.startswith(prefix):
                        shortname = name[len(prefix):]
                        if shortname in classdict:
                            warnings.warn("Conflicting name {}, ignoring".format(shortname))
                        else:
                            classdict[shortname] = staticmethod(attr) if callable(attr) else attr
                        break

        # Add enum constant defs
        if ffi:
            for name in dir(lib):
                try:
                    attr = getattr(lib, name)
                except AttributeError:
                    continue  # This could happen if multiple ffi libs are sharing headers

                if not isinstance(attr, ffi.CData) or ffi.typeof(attr).kind != 'function':
                    for prefix in base_flags['prefix']:
                        if name.startswith(prefix):
                            shortname = name[len(prefix):]
                            if shortname in classdict:
                                warnings.warn("Conflicting name {}, ignoring".format(shortname))
                            else:
                                classdict[shortname] = attr
                            break

        classdict['_dir_lib'] = dir_lib
        cls = super(LibMeta, metacls).__new__(metacls, clsname, bases, classdict)

        if test_mode_is('run'):
            _contingent_libs.append(cls)

        return cls

    @classmethod
    def __new_replay__(metacls, clsname, bases, orig_classdict):
        print("In __new_replay__()")
        classdict = {}
        return super(LibMeta, metacls).__new__(metacls, clsname, bases, classdict)

    def __getattr__(self, name):
        if test_mode_is('replay'):
            Record.ensure_created()
            value = Record.record.get_attr(name)
        else:
            value = getattr(self._ffilib, name)
            if test_mode_is('record'):
                Record.ensure_created()
                Record.record.add_attr_access(name, value)

        return value

    def __dir__(self):
        return list(self.__dict__.keys()) + self._dir_lib

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
    def __init__(self, func, repr_str, handles=(), niceobj_name=None, niceobj=None):
        self.__name__ = niceobj_name + '.' + func.__name__ if niceobj_name else func.__name__
        self._func = func
        self._repr = repr_str
        self._handles = handles
        self._niceobj = niceobj

    def __call__(self, *args):
        result = self._func(*(self._handles + args), niceobj=self._niceobj)

        if test_mode_is('record', 'replay'):
            Record.ensure_created()
            if test_mode_is('record'):
                Record.record.add_func_call(self.__name__, self._handles, args, result)
            else:  # replay
                raise NotImplementedError

        return result

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
    _info
        A `LibInfo` object that contains access to the underlying library and macros. Required
        (unless you are using the old-style `_ffi`, `_ffilib`, and `_defs` attributes)
    _ffi
        FFI instance variable. Required if not using `_info`
    _ffilib
        FFI library opened with `dlopen()`. Required if not using `_info`.
    _defs
        ``dict`` containing the Python-equivalent macros defined in the header file(s). Optional and
        only used if not using `_info`.
    _prefix : str or sequence of strs, optional
        Prefix(es) to strip from the library function names. E.g. If the library has functions
        named like ``SDK_Func()``, you can set `_prefix` to ``'SDK_'``, and access them as
        `Func()`. If more than one prefix is given, they are tried in order for each signature
        until the appropraite function is found.
    _ret : function or str, optional
        Wrapper function to handle the return values of each library function. By default, the
        return value will be appended to the end of the Python return values. The wrapper function
        takes the C function's return value (often an error/success code) as its only argument. If
        the wrapper returns a non-``None`` value, it will be appended to the wrapped function's
        return values.

        You may also use a ``str`` instead. If you define function ``_ret_foo()`` in your
        subclass, you may refer to it by using the ``str`` ``'foo'``.

        There are two wrappers that ``NiceLib`` defines for convenience (and may also be referenced
        as strings). ``_ret_return()`` is the default, which simply appends the return value to the
        wrapped function's return values, and ``_ret_ignore()``, which ignores the value entirely
        and does not return it.
    _struct_maker : function, optional
        Function that is called to create an FFI struct of the given type. Mainly useful for
        odd libraries that require you to always fill out some field of the struct, like its size
        in bytes
    _buflen : int, optional
        The default length for buffers. This can be overridden on a per-argument basis in the
        argument's spec string, e.g `'len=64'` will make a 64-byte buffer.
    _use_numpy : bool, optional
        If true, convert output args marked as 'arr' to ``numpy`` arrays. Obviously requires
        ``numpy`` to be installed.
    """
    _ffi = None  # MUST be filled in by subclass
    _ffilib = None  # MUST be filled in by subclass
    _defs = None
    _prefix = ''
    _struct_maker = None  # ffi.new
    _buflen = 512
    _use_numpy = False
    _free_buf = None
    _ret = 'return'

    def _ret_return(retval):
        return retval

    def _ret_ignore(retval):
        pass

    def __new__(cls):
        raise TypeError("Not allowed to instantiate {}. Use the class directly".format(cls))
