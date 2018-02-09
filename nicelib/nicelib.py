# -*- coding: utf-8 -*-
# Copyright 2015-2018 Nate Bogdanowicz
from __future__ import division, absolute_import, with_statement, print_function, unicode_literals

from builtins import str, zip
from past.builtins import basestring
from future.utils import with_metaclass

import re
import sys
import warnings
import logging
from inspect import isfunction, getargspec

from .util import to_tuple, ChainMap

__all__ = ['NiceLib', 'NiceObjectDef']
FLAGS = ('prefix', 'ret', 'struct_maker', 'buflen', 'use_numpy', 'free_buf')
log = logging.getLogger(__name__)

ARG_HANDLERS = []


def register_arg_handler(arg_handler):
    ARG_HANDLERS.append(arg_handler)


def c_to_numpy_array(ffi, c_arr, size):
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


class Sig(object):
    @classmethod
    def from_tuple(cls, sig_tup):
        # Allow non-tuple, e.g. ('in') or ({'ret':'ignore'})
        if not isinstance(sig_tup, tuple):
            sig_tup = (sig_tup,)

        if sig_tup and isinstance(sig_tup[-1], dict):
            sig_flags = sig_tup[-1]
            sig_tup = sig_tup[:-1]
        else:
            sig_flags = {}

        return cls(*sig_tup, **sig_flags)

    def __init__(self, *arg_strs, **flags):
        self.arg_strs = arg_strs
        self.sig_flags = flags
        self._make_arg_handlers()

    def __repr__(self):
        return "<Sig({})>".format(', '.join(repr(s) for s in self.arg_strs))

    def set_default_flags(self, flags_list):
        self.flags = ChainMap(self.sig_flags, *flags_list)

    def _make_arg_handlers(self):
        log.info('Making handlers for signature {}'.format(self.arg_strs))
        for handler_class in ARG_HANDLERS:
            handler_class.start_sig_definition()

        self.handlers = []
        self.sig_handlers = []
        for c_index, arg_str in enumerate(self.arg_strs):
            handler = self._make_arg_handler(arg_str, c_index)
            if handler in self.handlers:
                handler.c_indices += (c_index,)
            else:
                handler.c_indices = (c_index,)
                self.handlers.append(handler)
            self.sig_handlers.append(handler)

        for handler_class in ARG_HANDLERS:
            handler_class.end_sig_definition()

        self.handler_inargs = {}
        inarg_index = 0
        for sig_index, handler in enumerate(self.sig_handlers):
            num_inputs = handler.num_inputs_used(sig_index)
            new_indices = tuple(range(inarg_index, inarg_index+num_inputs))
            self.handler_inargs[handler] = self.handler_inargs.get(handler, ()) + new_indices
            inarg_index += num_inputs
        log.info('handler_inargs: %s', self.handler_inargs)
        self.num_inargs = inarg_index

    def _make_arg_handler(self, arg_str, arg_index):
        for handler_class in ARG_HANDLERS:
            handler = handler_class.create(self, arg_str, arg_index)
            if handler:
                return handler
        raise ValueError("Unrecognized argtype string '{}'".format(arg_str))

    def bind_argtypes(self, ffi, func_name, c_argtypes, ret_handler):
        self.ffi = ffi
        self.ret_handler = ret_handler
        self.c_argtypes = c_argtypes

        if len(self.arg_strs) != len(c_argtypes):
            raise TypeError("{}() takes {} args, but your signature specifies "
                            "{}".format(func_name, len(c_argtypes), len(self.arg_strs)))

        self.used_ret_handler_args = set(getargspec(ret_handler).args[1:])

        for sig_index, (handler, c_argtype) in enumerate(zip(self.handlers, c_argtypes)):
            if not hasattr(handler, 'c_argtypes'):
                handler.c_argtypes = (c_argtype,)
            else:
                handler.c_argtypes += (c_argtype,)

    def make_c_args(self, args):
        c_args = []
        arg_index = 0
        for arg_index, handler in enumerate(self.sig_handlers):
            inarg_indices = self.handler_inargs[handler]
            inargs = [args[i] for i in inarg_indices]
            log.info("Making cffi arg for %s", handler)
            c_args.append(handler.make_cffi_arg(self.ffi, arg_index, inargs))
        return c_args

    def get_outputs(self, c_args, retval, ret_handler_args):
        out_vals = []
        for sig_index, (handler, c_arg) in enumerate(zip(self.sig_handlers, c_args)):
            out_vals.extend(handler.get_outputs(self.ffi, sig_index, c_arg))

        if self.ret_handler:
            try:
                ret_handler_kwds = {arg: ret_handler_args[arg]
                                    for arg in self.used_ret_handler_args}
            except KeyError as e:
                raise KeyError("Unknown arg '{}' in arglist of ret-handling function "
                               "'{}'".format(e.args[0], self.ret_handler.__name__))
            retval = self.ret_handler(retval, **ret_handler_kwds)

        if retval is not None:
            out_vals.append(retval)

        if not out_vals:
            return None
        elif len(out_vals) == 1:
            return out_vals[0]
        else:
            return tuple(out_vals)


class ArgHandler(object):
    handlers = []

    @classmethod
    def start_sig_definition(cls):
        pass

    @classmethod
    def end_sig_definition(cls):
        pass

    @classmethod
    def create(cls, sig, arg_str, arg_index):
        raise NotImplementedError

    def __init__(self, sig, arg_str, arg_index):
        self.sig = sig
        self.arg_str = arg_str
        self.arg_index = arg_index

    def __repr__(self):
        return "<{}>".format(self.__class__.__name__)

    def num_inputs_used(self, arg_index):
        raise NotImplementedError

    def make_cffi_arg(self, ffi, arg_index, arg_values):
        raise NotImplementedError

    def get_outputs(self, ffi, arg_index, cffi_arg):
        raise NotImplementedError


@register_arg_handler
class InArgHandler(ArgHandler):
    @classmethod
    def create(cls, sig, arg_str, arg_index):
        if arg_str != 'in':
            return None
        return cls(sig, arg_str, arg_index)

    def num_inputs_used(self, arg_index):
        return 1

    def make_cffi_arg(self, ffi, arg_index, arg_values):
        arg_value, = arg_values
        return _wrap_inarg(ffi, self.c_argtypes[0], arg_value)

    def get_outputs(self, ffi, arg_index, cffi_arg):
        return ()


@register_arg_handler
class OutArgHandler(ArgHandler):
    @classmethod
    def create(cls, sig, arg_str, arg_index):
        if arg_str != 'out':
            return None
        return cls(sig, arg_str, arg_index)

    def num_inputs_used(self, arg_index):
        return 0

    def make_cffi_arg(self, ffi, arg_index, arg_values):
        if self.c_argtypes[0].kind == 'pointer' and self.c_argtypes[0].item.kind == 'struct':
            arg = self.sig.flags['struct_maker'](self.c_argtypes[0])
        else:
            arg = ffi.new(self.c_argtypes[0])
        return arg

    def get_outputs(self, ffi, arg_index, cffi_arg):
        return (cffi_arg[0],)


@register_arg_handler
class IgnoreArgHandler(ArgHandler):
    @classmethod
    def create(cls, sig, arg_str, arg_index):
        if arg_str == 'ignore':
            return cls(sig, arg_str, arg_index)
        else:
            return None

    def num_inputs_used(self, arg_index):
        return 0

    def make_cffi_arg(self, ffi, arg_index, arg_values):
        return ffi.new(self.c_argtypes[0].cname + '*')[0]

    def get_outputs(self, ffi, arg_index, cffi_arg):
        return ()


@register_arg_handler
class ArrayArgHandler(ArgHandler):
    RE_ARR = re.compile(r'arr(\[([0-9]+)\])?$')
    RE_BUF = re.compile(r'buf(\[([0-9]+)\])?$')
    RE_LEN = re.compile(r'len(=([0-9]+|in))?')

    @classmethod
    def start_sig_definition(cls):
        cls.unmatched_arrays = []
        # NOTE: Could also define unmatched_lens if we want to allow lens before arrs

    @classmethod
    def end_sig_definition(cls):
        cls.unmatched_arrays = None

    @classmethod
    def create(cls, sig, arg_str, arg_index):
        m = cls.RE_ARR.match(arg_str)
        if m:
            len_num = None if m.group(2) is None else int(m.group(2))
            handler = cls(sig, arg_str, arg_index, is_buf=False, fixed_len=len_num)
            if len_num is None:
                cls.unmatched_arrays.append(handler)
            return handler

        m = cls.RE_BUF.match(arg_str)
        if m:
            len_num = None if m.group(2) is None else int(m.group(2))
            handler = cls(sig, arg_str, arg_index, is_buf=True, fixed_len=len_num)
            if len_num is None:
                cls.unmatched_arrays.append(handler)
            return handler

        m = cls.RE_LEN.match(arg_str)
        if m:
            handler = cls.unmatched_arrays.pop(0)
            if m.group(2) is None:
                pass
            elif m.group(2) == 'in':
                handler.get_len = True
            else:
                handler.fixed_len = int(m.group(2))

            handler.len_argindex = arg_index
            return handler

        else:
            return None

    def num_inputs_used(self, arg_index):
        if arg_index == self.arr_argindex:
            return 0
        elif arg_index == self.len_argindex:
            return int(self.get_len)
        raise ValueError('Invalid arg_index')

    def __init__(self, sig, arg_str, arg_index, is_buf, fixed_len, get_len=False):
        ArgHandler.__init__(self, sig, arg_str, arg_index)
        self.is_buf = is_buf
        self.fixed_len = fixed_len
        self.get_len = get_len
        self.arr_argindex = arg_index
        self.len_argindex = None

    def len(self):
        if self.fixed_len:
            return self.fixed_len
        return self.sig.flags['buflen']
        # TODO: Figure out what to do for get_len

    def _get_arr_output(self, ffi, cffi_arg):
        if self.sig.flags['use_numpy']:
            return c_to_numpy_array(ffi, cffi_arg, self.len())
        else:
            return cffi_arg

    def get_outputs(self, ffi, arg_index, cffi_arg):
        if arg_index == self.arr_argindex:
            if self.is_buf:
                return (ffi.string(cffi_arg),)
            else:
                return (self._get_arr_output(ffi, cffi_arg),)
        else:
            return ()

    def make_cffi_arg(self, ffi, arg_index, arg_values):
        if arg_index == self.arr_argindex:
            if self.is_buf:
                return ffi.new('char[]', self.len())
            else:
                return ffi.new('{}[]'.format(self.c_argtypes[0].item.cname), self.len())

        elif arg_index == self.len_argindex:
            return self.len()

        else:
            raise ValueError('Invalid arg_index')


class NiceObject(object):
    _init_func = None
    _n_handles = None

    def __init__(self, *args):
        handles = self._init_func(*args) if self._init_func else args
        if not isinstance(handles, tuple):
            handles = (handles,)
        self._handles = handles

        if len(handles) != self._n_handles:
            raise TypeError("__init__() takes exactly {} arguments "
                            "({} given)".format(self._n_handles, len(handles)))

        ## Generate "bound methods"
        #for func_name in niceobjdef.names:
        #    if func_name in funcs:
        #        lib_func = LibFunction(funcs[func_name], repr_strs[func_name], handles,
        #                                cls_name, self)
        #        if func_name in user_funcs:
        #            wrapped_func = user_funcs[func_name]
        #            wrapped_func.orig = lib_func
        #            setattr(self, func_name, wrapped_func)
        #        else:
        #            setattr(self, func_name, lib_func)


class LibMethod(object):
    def __init__(self, niceobj, func):
        self._niceobj = niceobj
        self._func = func

    def __call__(self, *args):
        return self._func(*(self._niceobj._handles + args), niceobj=self._niceobj)


class NiceClassMeta(type):
    def __new__(metacls, cls_name, niceobjdef, parent_lib):
        try:
            init_func = parent_lib._libfuncs[niceobjdef.init] if niceobjdef.init else None
        except KeyError:
            raise ValueError("Could not find function '{}'".format(niceobjdef.init))

        niceobj_dict = {
            '_init_func': init_func,
            '_n_handles': niceobjdef.n_handles,
            '__doc__': niceobjdef.doc
        }
        for attr_name, attr_value in niceobjdef.attrs.items():
            if isinstance(attr_value, Sig):
                sig = attr_value
            else:
                sig = Sig.from_tuple(attr_value)
            sig.set_default_flags((niceobjdef.flags, parent_lib._base_flags))
            libfunc = parent_lib._create_libfunction(attr_name, sig)
            niceobj_dict[attr_name] = libfunc
        return type(cls_name, (NiceObject,), niceobj_dict)


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


#def _cffi_wrapper(ffi, func, fname, sig_tup, prefix, ret, struct_maker, buflen,
#                  use_numpy, free_buf):
#    default_buflen = buflen
#    ret_handler_args = set(getargspec(ret).args[1:])
#
#    def bufout_wrap(buf_ptr):
#        """buf_ptr is a char**"""
#        if buf_ptr[0] == ffi.NULL:
#            return None
#
#        string = ffi.string(buf_ptr[0])
#        if free_buf:
#            free_buf(buf_ptr[0])
#        return string
#
#    def c_to_numpy_array(c_arr, size):
#        import numpy as np
#        arrtype = ffi.typeof(c_arr)
#        cname = arrtype.item.cname
#        if cname.startswith(('int', 'long', 'short', 'char', 'signed')):
#            prefix = 'i'
#        elif cname.startswith('unsigned'):
#            prefix = 'u'
#        elif cname.startswith(('float', 'double')):
#            prefix = 'f'
#        else:
#            raise TypeError("Unknown type {}".format(cname))
#
#        dtype = np.dtype(prefix + str(ffi.sizeof(arrtype.item)))
#        return np.frombuffer(ffi.buffer(c_arr), dtype=dtype)
#
#    arr_out_wrapper = c_to_numpy_array if use_numpy else (lambda arr, size: arr)
#
#    functype = ffi.typeof(func)
#    argtypes = functype.args
#    # Cast bytes to str
#    sig_tup = tuple(str(sig) if isinstance(sig, bytes) else sig for sig in sig_tup)
#    n_expected_inargs = sum('in' in a for a in sig_tup if isinstance(a, str))
#
#    if functype.ellipsis:
#        argtypes = argtypes + ('...',)
#
#    if len(sig_tup) != len(argtypes):
#        raise TypeError("{}() takes {} args, but your signature specifies "
#                        "{}".format(fname, len(argtypes), len(sig_tup)))
#
#    def wrapped(*inargs, **kwds):
#        inargs = list(inargs)
#        available_args = {}
#        available_args['niceobj'] = kwds.pop('niceobj', None)
#        available_args['funcname'] = fname
#
#        if not functype.ellipsis and len(inargs) != n_expected_inargs:
#            message = '{}() takes '.format(fname)
#            if n_expected_inargs == 0:
#                message += 'no arguments'
#            elif n_expected_inargs == 1:
#                message += '1 argument'
#            else:
#                message += '{} arguments'.format(n_expected_inargs)
#
#            message += ' ({} given)'.format(len(inargs))
#
#            raise TypeError(message)
#
#        # First pass to get buf/arr info
#        buflens, lens, solo_buflens, buftypes = [], [], [], []
#        n_paired_bufs = 0
#        inarg_idx = 0
#        for sig, argtype in zip(sig_tup, argtypes):
#            if argtype == '...':
#                continue
#
#            elif sig in ('buf', 'arr'):
#                n_paired_bufs += 1
#                buftypes.append(argtype.item)
#
#            elif sig.startswith(('buf[', 'arr[')):
#                try:
#                    assert sig[3] == '[' and sig[-1] == ']'
#                    num = int(sig[4:-1])
#                    assert num > 0
#                except (AssertionError, ValueError):
#                    raise ValueError("Bad sig element '{}'".format(sig))
#                solo_buflens.append(num)
#
#            elif sig.startswith('len'):
#                sig, _, size_type = sig.partition(':')
#
#                if len(sig) == 3:
#                    num = default_buflen
#                else:
#                    try:
#                        assert sig[3] == '='
#                        if sig[4:] == 'in':
#                            num = inargs[inarg_idx]
#                        else:
#                            num = int(sig[4:])
#                    except (AssertionError, ValueError):
#                        raise ValueError("Bad sig element '{}'".format(sig))
#                lens.append(num)
#                buflens.append(num)
#
#            if 'in' in sig:
#                inarg_idx += 1
#
#        if len(lens) != n_paired_bufs:
#            raise ValueError("Number of paired buf/arr sig elements does not match number of "
#                             "len sig elements")
#
#        outargs = []
#        args = []
#        bufs = []
#        # Possible sig entries:
#        # - in
#        # - out
#        # - inout
#        # - buf[n]  (c-string buffer)
#        # - arr[n]  (array)
#        # - len=n   (length of buf/arr)
#        # - retlen??(returned length)
#        # - ignore  (reserved arg, pass in 0/NULL)
#        for info, argtype in zip(sig_tup, argtypes):
#            if argtype == '...':
#                info, argtype = info(*args)
#
#            if info == 'inout':
#                inarg = inargs.pop(0)
#                try:
#                    # FIXME: This could misbehave if the user passes a typename string (e.g. 'int')
#                    inarg_type = ffi.typeof(inarg)
#                except TypeError:
#                    inarg_type = type(inarg)
#
#                if argtype == inarg_type:
#                    arg = inarg  # Pass straight through
#                elif argtype.kind == 'pointer' and argtype.item.kind == 'struct':
#                    arg = struct_maker(argtype, inarg)
#                elif (argtype.cname == 'void *' and isinstance(inarg, ffi.CData) and
#                      inarg_type.kind in ('pointer', 'array')):
#                    arg = ffi.cast(argtype, inarg)
#                else:
#                    try:
#                        arg = ffi.new(argtype, inarg)
#                    except TypeError:
#                        raise TypeError("Cannot convert {} to required type"
#                                        "{}".format(inarg, argtype))
#
#                if argtype.kind == 'pointer' and argtype.item.cname == 'void':
#                    # Don't dereference void pointers directly
#                    outargs.append((arg, lambda o: o))
#                else:
#                    outargs.append((arg, lambda o: o[0]))
#            elif info == 'in':
#                arg = inargs.pop(0)
#                arg = _wrap_inarg(ffi, argtype, arg)
#            elif info == 'out':
#                if argtype.kind == 'pointer' and argtype.item.kind == 'struct':
#                    arg = struct_maker(argtype)
#                else:
#                    arg = ffi.new(argtype)
#                outargs.append((arg, lambda o: o[0]))
#            elif info == 'bufout':
#                if not (argtype.kind == 'pointer' and argtype.item.kind == 'pointer' and
#                        argtype.item.item.kind == 'primitive'):
#                    raise TypeError("'bufout' applies only to type 'char**'")
#                arg = ffi.new(argtype)
#                outargs.append((arg, bufout_wrap))
#            elif info.startswith('buf'):
#                buflen = (buflens if len(info) == 3 else solo_buflens).pop(0)
#                arg = ffi.new('char[]', buflen)
#                outargs.append((arg, lambda o: ffi.string(o)))
#                bufs.append(arg)
#            elif info.startswith('arr'):
#                buflen = (buflens if len(info) == 3 else solo_buflens).pop(0)
#                arg = ffi.new('{}[]'.format(argtype.item.cname), buflen)
#                outargs.append((arg, lambda arr: arr_out_wrapper(arr, buflen)))
#                bufs.append(arg)
#            elif info.startswith('len'):
#                info, _, size_type = info.partition(':')
#                if info == 'len=in':
#                    inargs.pop(0)  # We've already used this earlier
#                buftype = buftypes.pop(0)
#
#                # Adjust len if sig has an explicit type
#                if not size_type:
#                    meas_size = ffi.sizeof(buftype)
#                elif size_type == 'byte':
#                    meas_size = 1
#                else:
#                    meas_size = ffi.sizeof(size_type)
#
#                arg = lens.pop(0) * ffi.sizeof(buftype) // meas_size
#            elif info == 'ignore':
#                arg = ffi.new(argtype.cname + '*')[0]
#            else:
#                raise Exception("Unrecognized arg info '{}'".format(info))
#
#            if isinstance(arg, str):
#                arg = arg.encode('ascii')
#            args.append(arg)
#
#        available_args['funcargs'] = args
#
#        retval = func(*args)
#        out_vals = [f(a) for a, f in outargs]
#
#        if ret:
#            try:
#                kwds = {arg: available_args[arg] for arg in ret_handler_args}
#            except KeyError as e:
#                raise KeyError("Unknown arg '{}' in arglist of ret-handling function "
#                               "'{}'".format(e.args[0], ret.__name__))
#            retval = ret(retval, **kwds)
#
#        if retval is not None:
#            out_vals.append(retval)
#
#        if not out_vals:
#            return None
#        elif len(out_vals) == 1:
#            return out_vals[0]
#        else:
#            return tuple(out_vals)
#
#    wrapped.__name__ = fname
#    wrapped._ffi_func = func
#    wrapped._sig_tup = sig_tup
#    return wrapped


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
            warnings.warn("The 'ret_wrap' flag has been renamed to 'ret', please update your code:",
                          stacklevel=2)
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
        return "<NiceObjectDef values={}>".format(repr(self.names))

    def __repr__(self):
        return "<NiceObjectDef values={}>".format(repr(self.names))


class LibMeta(type):
    def __new__(metacls, clsname, bases, orig_classdict):
        classdict = {}
        niceobjectdefs = {}  # name: NiceObjectDef
        sigs = {}

        for name, value in orig_classdict.items():
            log.info("Processing attr '{}'...".format(name))
            if isinstance(value, NiceObjectDef):
                if value.attrs is None:
                    value.names.remove(name)  # Remove self (context manager syntax)
                niceobjectdefs[name] = value

            elif isfunction(value):
                if hasattr(value, 'sig'):
                    sigs[name] = value.sig
                else:
                    # Ordinary function (includes ret-handlers)
                    classdict[name] = staticmethod(value)

            elif isinstance(value, Sig):
                sigs[name] = value

            elif not name.startswith('_'):
                sigs[name] = Sig.from_tuple(value)

            else:
                classdict[name] = value

        classdict.update(_niceobjectdefs=niceobjectdefs, _sigs=sigs)
        print('classdict: {}'.format(classdict))
        return super(LibMeta, metacls).__new__(metacls, clsname, bases, classdict)

    def __init__(cls, clsname, bases, classdict):
        print('bases: {}'.format(bases))
        if bases == (object,):
            return  # Base class

        cls._handle_deprecated_attributes()
        if '_info' in cls.__dict__:
            cls._ffi = cls._info._ffi
            cls._ffilib = cls._info._ffilib
            cls._defs = cls._info._defs
        else:
            cls._ffilib = cls._lib
            del cls._lib

        cls._handle_base_flags()
        cls._add_dir_ffilib()
        cls._add_ret_handlers()
        cls._create_libfunctions()
        cls._create_niceobject_classes()
        cls._add_enum_constant_defs()
        cls._add_macro_defs()

    def _handle_deprecated_attributes(cls):
        # FIXME: remove __dict__.pop()
        if '_err_wrap' in cls.__dict__:
            cls._ret = cls.__dict__.pop('_err_wrap')
            warnings.warn("Your class defines _err_wrap, which has been renamed to _ret, "
                          "please update your code:", stacklevel=2)

        if '_ret_wrap' in cls.__dict__:
            cls._ret = cls.__dict__.pop('_ret_wrap')
            warnings.warn("Your class defines _ret_wrap, which has been renamed to _ret, "
                          "please update your code:", stacklevel=2)

    def _add_ret_handlers(cls):
        cls._ret_handlers = {}
        for attr_name in dir(cls):
            if attr_name.startswith('_ret_'):
                cls._ret_handlers[attr_name[5:]] = getattr(cls, attr_name)

    def _handle_base_flags(cls):
        cls._base_flags = {flag_name: getattr(cls, '_' + flag_name) for flag_name in FLAGS}

        if cls._ffi and not cls._base_flags['struct_maker']:
            cls._base_flags['struct_maker'] = cls._ffi.new

        # Add default empty prefix
        cls._base_flags['prefix'] = to_tuple(cls._base_flags['prefix'])
        if '' not in cls._base_flags['prefix']:
            cls._base_flags['prefix'] += ('',)

    def _add_dir_ffilib(cls):
        cls._dir_ffilib = []
        for name in dir(cls._ffilib):
            try:
                attr = getattr(cls._ffilib, name)
                if (cls._ffi and isinstance(attr, cls._ffi.CData) and
                        cls._ffi.typeof(attr).kind != 'function'):
                    cls._dir_ffilib.append(name)
            except Exception as e:
                # The error types cffi uses seem to keep changing, so just catch all of them
                log.info("Name '%s' found in headers, but not this dll: %s", name, e)
            log.debug("Handling NiceLib attr '%s'", name)

    def _create_libfunctions(cls):
        cls._libfuncs = {}
        for shortname, sig in cls._sigs.items():
            sig.set_default_flags([cls._base_flags])
            libfunc = cls._create_libfunction(shortname, sig)
            if libfunc:
                setattr(cls, shortname, libfunc)
                cls._libfuncs[shortname] = libfunc

    def _create_libfunction(cls, shortname, sig):
        # Designed to be called by NiceLib and NiceClassMeta
        prefixes = sig.flags.get('prefix', ())
        try:
            cffi_func, _ = cls._find_cffi_func(shortname, prefixes)
        except ValueError:
            return None

        c_functype = cls._ffi.typeof(cffi_func)
        c_argtypes = c_functype.args
        if c_functype.ellipsis:
            c_argtypes = c_argtypes + ('...',)

        ret_handler = sig.flags['ret']
        if isinstance(ret_handler, basestring):
            ret_handler = cls._ret_handlers[ret_handler]

        sig.bind_argtypes(cls._ffi, shortname, c_argtypes, ret_handler)

        return LibFunction(shortname, sig, cffi_func)

    def _find_cffi_func(cls, shortname, prefixes):
        for prefix in prefixes:
            func_name = prefix + shortname
            try:
                return getattr(cls._ffilib, func_name), func_name
            except AttributeError:
                pass
        raise ValueError("No lib function found with a name ending in '{}', with "
                         "any of these prefixes: {}".format(shortname, prefixes))

    def _create_niceobject_classes(cls):
        for niceobj_cls_name, niceobjdef in cls._niceobjectdefs.items():
            niceobj_cls = NiceClassMeta(niceobj_cls_name, niceobjdef, cls)
            setattr(cls, niceobj_cls_name, niceobj_cls)

    def _add_enum_constant_defs(cls):
        prefixes = cls._base_flags['prefix']
        for name in dir(cls._ffilib):
            try:
                attr = getattr(cls._ffilib, name)
            except:
                # The error types cffi uses seem to keep changing, so just catch all of them
                log.info("Name '%s' found in headers, but not this dll", name)
                continue  # This could happen if multiple ffi libs are sharing headers

            if not isinstance(attr, cls._ffi.CData) or cls._ffi.typeof(attr).kind != 'function':
                prefix, shortname = unprefix(name, prefixes)
                if shortname in cls.__dict__:
                    warnings.warn("Conflicting name {}, ignoring".format(shortname))
                else:
                    setattr(cls, shortname, attr)

    def _add_macro_defs(cls):
        prefixes = cls._base_flags['prefix']
        for full_name, attr in cls._defs.items():
            prefix, name = unprefix(full_name, prefixes)
            if name in cls.__dict__:
                warnings.warn("Conflicting name {}, ignoring".format(name))
            else:
                macro = staticmethod(attr) if callable(attr) else attr
                setattr(cls, name, macro)

    def __getattr__(cls, name):
        if name in cls._dir_ffilib:
            return getattr(cls._ffilib, name)
        raise AttributeError("{} has no attribute named '{}'".format(cls.__name__, name))

    def __dir__(self):
        return list(self.__dict__.keys()) + self._dir_ffilib


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


class OldLibFunction(object):
    def __init__(self, func, repr_str, handles=(), niceobj_name=None, niceobj=None):
        self.__name__ = niceobj_name + '.' + func.__name__ if niceobj_name else func.__name__
        self._func = func
        self._repr = repr_str
        self._handles = handles
        self._niceobj = niceobj

    def __call__(self, *args):
        return self._func(*(self._handles + args), niceobj=self._niceobj)

    def __str__(self):
        return self._repr

    def __repr__(self):
        return self._repr


def unprefix(name, prefixes):
    for prefix in prefixes:
        if name.startswith(prefix):
            return prefix, name[len(prefix):]
    return '', name


class LibFunction(object):
    def __init__(self, name, sig, c_func):
        self.sig = sig
        self.name = name
        self.c_func = c_func

    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            return LibMethod(instance, self)

    def __call__(self, *args, **kwds):
        if len(args) != self.sig.num_inargs:
            raise TypeError("{}() takes {} arguments ({} given)"
                            "".format(self.name, self.sig.num_inargs, len(args)))

        ret_handler_args = {
            'niceobj': kwds.pop('niceobj', None),
            'funcname': self.name,
        }

        c_args = self.sig.make_c_args(args)
        retval = self.c_func(*c_args)
        return self.sig.get_outputs(c_args, retval, ret_handler_args)


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
