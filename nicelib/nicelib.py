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
from collections import deque

from .util import to_tuple, ChainMap, suppress

log = logging.getLogger(__name__)

__all__ = ['NiceLib', 'NiceObjectDef']
FLAGS = {'prefix', 'ret', 'struct_maker', 'buflen', 'use_numpy', 'free_buf'}
UNDER_FLAGS = {'_{}_'.format(f) for f in FLAGS}
USINGLE_FLAGS = {'_'+f for f in FLAGS}
COMBINED_FLAGS = UNDER_FLAGS | USINGLE_FLAGS
ARG_HANDLERS = []


def register_arg_handler(arg_handler):
    ARG_HANDLERS.append(arg_handler)
    return arg_handler


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
        self._num_default_args = 0
        self._make_arg_handlers()

    def __repr__(self):
        return "<Sig({})>".format(', '.join(repr(s) for s in self.arg_strs))

    def args_c_str(self):
        return ', '.join(h.arg_c_str for h in self.handlers)

    def args_py_str(self, skipargs=0):
        return ', '.join(h.arg_py_str for h in self.handlers[skipargs:] if h.takes_input)

    def rets_py_str(self):
        n_outputs = len(self.out_handlers)
        if n_outputs == 0:
            return 'None'
        elif n_outputs == 1:
            return self.out_handlers[0].arg_py_str
        else:
            return '(' + ', '.join(h.arg_py_str for h in self.out_handlers) + ')'

    def set_default_flags(self, flags_list):
        self.flags = ChainMap(self.sig_flags, *flags_list)

    def _make_arg_handlers(self):
        log.info('Making handlers for signature {}'.format(self.arg_strs))
        for handler_class in ARG_HANDLERS:
            handler_class.start_sig_definition()

        self.handlers = [self._make_arg_handler(arg_str) for arg_str in self.arg_strs]

        for handler_class in ARG_HANDLERS:
            handler_class.end_sig_definition()

        self.in_handlers = [h for h in self.handlers if h.takes_input]
        self.out_handlers = [h for h in self.handlers if h.makes_output]
        self.num_inargs = len(self.in_handlers)

    def _make_arg_handler(self, arg_str):
        for handler_class in ARG_HANDLERS:
            handler = handler_class.create(self, arg_str)
            if handler:
                return handler
        raise ValueError("Unrecognized argtype string '{}'".format(arg_str))

    def bind_argtypes(self, ffi, func_name, c_argtypes, ret_handler, c_argnames):
        self.ffi = ffi
        self.func_name = func_name
        self.c_argtypes = c_argtypes
        self.ret_handler = ret_handler
        self.c_argnames = c_argnames
        self.variadic = (c_argtypes and c_argtypes[-1] == '...')

        if self.variadic:
            if len(self.arg_strs) < len(c_argtypes) - 1:
                raise TypeError("{}() takes at least {} args, but your signature specifies "
                                "{}".format(func_name, len(c_argtypes)-1, len(self.arg_strs)))
        else:
            if len(self.arg_strs) != len(c_argtypes):
                raise TypeError("{}() takes {} args, but your signature specifies "
                                "{}".format(func_name, len(c_argtypes), len(self.arg_strs)))

        self.argnames = []
        self.retnames = []
        c_argnames = c_argnames or [None] * len(c_argtypes)
        for handler, c_argtype, c_argname in zip(self.handlers, c_argtypes, c_argnames):
            handler.c_argtype = c_argtype
            handler.c_argname = c_argname or self._next_default_argname()
            if handler.takes_input:
                self.argnames.append(c_argname)
            if handler.makes_output:
                self.retnames.append(c_argname)

    def _next_default_argname(self):
        self._num_default_args += 1
        return 'arg{}'.format(self._num_default_args)

    def make_c_args(self, args):
        py_args = deque(args)
        c_args = []
        for handler in self.handlers:
            log.info("Making C arg for %s", handler)
            py_arg = py_args.popleft() if handler.takes_input else None
            c_args.append(handler.make_c_arg(self.ffi, py_arg))

        # Do second pass to clean up callables; beware that cdata can be callable though
        return [a() if (not isinstance(a, self.ffi.CData) and callable(a)) else a for a in c_args]

    def extract_outputs(self, c_args, retval, ret_handler_kwargs):
        out_vals = [handler.extract_output(self.ffi, c_arg)
                    for handler, c_arg in zip(self.handlers, c_args)
                    if handler.makes_output]

        if self.ret_handler:
            retval = self.ret_handler.handle(retval, ret_handler_kwargs)

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
    def create(cls, sig, arg_str):
        raise NotImplementedError

    def __init__(self, sig, arg_str):
        self.sig = sig
        self.arg_str = arg_str

    def __repr__(self):
        return "<{}>".format(self.__class__.__name__)

    @property
    def arg_c_str(self):
        arg_str = self.c_argtype.cname
        if self.c_argname:
            arg_str += ' ' + self.c_argname
        return arg_str

    @property
    def arg_py_str(self):
        return self.c_argname or 'arg'

    def make_c_arg(self, ffi, arg_value):
        raise NotImplementedError

    def extract_output(self, ffi, c_arg):
        raise NotImplementedError


@register_arg_handler
class InArgHandler(ArgHandler):
    takes_input = True
    makes_output = False

    @classmethod
    def create(cls, sig, arg_str):
        if arg_str != 'in':
            return None
        return cls(sig, arg_str)

    def make_c_arg(self, ffi, arg_value):
        return _wrap_inarg(ffi, self.c_argtype, arg_value)


@register_arg_handler
class OutArgHandler(ArgHandler):
    takes_input = False
    makes_output = True

    @classmethod
    def create(cls, sig, arg_str):
        if arg_str != 'out':
            return None
        return cls(sig, arg_str)

    def make_c_arg(self, ffi, arg_value):
        if self.c_argtype.kind == 'pointer' and self.c_argtype.item.kind == 'struct':
            arg = self.sig.flags['struct_maker'](self.c_argtype)
        else:
            arg = ffi.new(self.c_argtype)
        return arg

    def extract_output(self, ffi, c_arg):
        return c_arg[0]


@register_arg_handler
class InOutArgHandler(ArgHandler):
    takes_input = True
    makes_output = True

    @classmethod
    def create(cls, sig, arg_str):
        if arg_str == 'inout':
            return cls(sig, arg_str)

    def make_c_arg(self, ffi, arg_value):
        inarg_type = (ffi.typeof(arg_value) if isinstance(arg_value, ffi.cdata) else
                      type(arg_value))

        if inarg_type == self.c_argtype:
            return arg_value  # Pass straight through

        if self.c_argtype.kind == 'pointer' and self.c_argtype.item.kind == 'struct':
            struct_maker = self.sig.flags['struct_maker']
            return struct_maker(self.c_argtype, arg_value)

        if (self.c_argtype.cname == 'void *' and isinstance(arg_value, ffi.CData) and
                inarg_type.kind in ('pointer', 'array')):
            return ffi.cast(self.c_argtype, arg_value)

        try:
            return ffi.new(self.c_argtype, arg_value)
        except TypeError:
            raise TypeError("Cannot convert {} to required type {}"
                            "".format(arg_value, self.c_argtype))

    def extract_output(self, ffi, c_arg):
        if self.c_argtype.cname == 'void *':
            return c_arg  # Don't dereference void pointers directly
        else:
            return c_arg[0]


@register_arg_handler
class IgnoreArgHandler(ArgHandler):
    takes_input = False
    makes_output = False

    @classmethod
    def create(cls, sig, arg_str):
        if arg_str == 'ignore':
            return cls(sig, arg_str)
        else:
            return None

    def make_c_arg(self, ffi, arg_value):
        return ffi.new(self.c_argtype.cname + '*')[0]


@register_arg_handler
class ArrayLenArgHandler(ArgHandler):
    RE_LEN = re.compile(r'len(=([0-9]+|in))?')

    @property
    def takes_input(self):
        return self.get_len

    makes_output = False

    @classmethod
    def create(cls, sig, arg_str):
        m = cls.RE_LEN.match(arg_str)
        if m:
            len_handler = cls(sig, arg_str)
            arr_handler = ArrayArgHandler.unmatched_arrays.pop(0)
            len_handler.arr_handler = arr_handler
            arr_handler.len_handler = len_handler

            len_param = m.group(2)

            len_handler.get_len = False
            len_handler.fixed_len = None
            if len_param == 'in':
                len_handler.get_len = True
            elif len_param is not None:
                len_handler.fixed_len = int(len_param)

            return len_handler
        else:
            return None

    def make_c_arg(self, ffi, arg_value):
        # Save len for later use by ArrayArgHandler
        if self.get_len:
            self.len = arg_value
        elif self.fixed_len:
            self.len = self.fixed_len
        else:
            self.len = self.sig.flags['buflen']
        return self.len


@register_arg_handler
class ArrayArgHandler(ArgHandler):
    RE_ARR = re.compile(r'(arr|buf)(\[([0-9]+)\])?$')

    takes_input = False
    makes_output = True

    @classmethod
    def start_sig_definition(cls):
        cls.unmatched_arrays = []
        # NOTE: Could also define unmatched_lens if we want to allow lens before arrs

    @classmethod
    def end_sig_definition(cls):
        if cls.unmatched_arrays:
            raise ValueError("Number of paired buf/arr sig elements does not match number of "
                             "len sig elements")
        cls.unmatched_arrays = None

    @classmethod
    def create(cls, sig, arg_str):
        m = cls.RE_ARR.match(arg_str)
        if m:
            is_buf = (m.group(1) == 'buf')
            len_num = None if m.group(3) is None else int(m.group(3))
            handler = cls(sig, arg_str, is_buf, len_num)
            if len_num is None:
                cls.unmatched_arrays.append(handler)
            return handler
        return None

    def __init__(self, sig, arg_str, is_buf, given_len):
        ArgHandler.__init__(self, sig, arg_str)
        self.is_buf = is_buf
        self.given_len = given_len
        self.len_handler = None

    def extract_output(self, ffi, c_arg):
        if self.is_buf:
            return ffi.string(c_arg)
        elif self.sig.flags['use_numpy']:
            return c_to_numpy_array(ffi, c_arg, self.len())
        else:
            return c_arg

    def len(self):
        if self.given_len:
            return self.given_len
        else:
            return self.len_handler.len

    def make_c_arg(self, ffi, arg_value):
        if self.is_buf:
            return lambda: ffi.new('char[]', self.len())
        else:
            return lambda: ffi.new('{}[]'.format(self.c_argtype.item.cname), self.len())


@register_arg_handler
class BufOutArgHandler(ArgHandler):
    takes_input = False
    makes_output = True

    @classmethod
    def create(cls, sig, arg_str):
        if arg_str == 'bufout':
            return cls(sig, arg_str)

    def make_c_arg(self, ffi, arg_value):
        if not (self.c_argtype.kind == 'pointer' and self.c_argtype.item.kind == 'pointer' and
                self.c_argtype.item.item.kind == 'primitive'):
            raise TypeError("'bufout' applies only to type 'char**'")
        return ffi.new(self.c_argtype)

    def extract_output(self, ffi, c_arg):
        if c_arg[0] == ffi.NULL:
            return None
        string = ffi.string(c_arg[0])

        free_buf = self.sig.args['free_buf']
        if free_buf:
            free_buf(c_arg[0])
        return string


class RetHandler(object):
    def __init__(self, func=None, name=None, num_retvals=None):
        self.__name__ = name
        self.num_retvals = num_retvals
        if func:
            self(func)

    def __call__(self, func):
        self._func = func
        if hasattr(func, '__name__') and not self.__name__:
            self.__name__ = func.__name__

        self.kwargs = set(getargspec(func).args[1:])
        return self

    def __repr__(self):
        return '<RetHandler(name={!r})>'.format(self.__name__)

    def handle(self, retval, available_kwargs):
        try:
            kwargs = {arg:available_kwargs[arg] for arg in self.kwargs}
        except KeyError as e:
            raise KeyError("Unknown arg '{}' in arglist of ret-handling function "
                           "'{}'".format(e.args[0], self.ret_handler.__name__))
        return self._func(retval, **kwargs)


@RetHandler(num_retvals=1)
def ret_return(retval):
    return retval


@RetHandler(num_retvals=0)
def ret_ignore(retval):
    pass


class NiceObjectMeta(type):
    def __new__(metacls, clsname, bases, classdict):
        if bases == (object,):
            return type.__new__(metacls, clsname, bases, classdict)  # Base class

        flags = {f.strip('_'):classdict.pop(f) for f in UNDER_FLAGS if f in classdict}
        metacls._handle_flags(flags)
        classdict['_flags'] = flags
        classdict.setdefault('_n_handles', classdict.pop('_n_handles_', 1))

        return type.__new__(metacls, clsname, bases, classdict)

    @classmethod
    def _handle_flags(metacls, flags):
        with suppress(KeyError):
            flags['prefix'] = to_tuple(flags['prefix'])

    def _patch(cls, parent_lib):
        if hasattr(cls, '_init_'):
            init = cls._init_
            if isinstance(init, basestring):
                init = getattr(parent_lib, init)
            cls._init_func = staticmethod(init)

        for attr_name, attr_value in list(cls.__dict__.items()):
            if isinstance(attr_value, Sig):
                sig = attr_value
                sig.set_default_flags((cls._flags, parent_lib._base_flags))
                libfunc = parent_lib._create_libfunction(attr_name, sig)

                if not libfunc:
                    log.warn("Function '%s' could not be found using prefixes %r",
                             attr_name, sig.flags['prefix'])
                setattr(cls, attr_name, libfunc)

    @classmethod
    def from_niceobjectdef(metacls, cls_name, niceobjdef, parent_lib):
        classdict = {
            '_init_': niceobjdef.init,
            '_n_handles_': niceobjdef.n_handles,
            '__doc__': niceobjdef.doc,
        }
        classdict.update({('_'+f+'_'):v for f,v in niceobjdef.flags.items()})
        classdict.update(niceobjdef.attrs)

        cls = NiceObjectMeta(cls_name, (NiceObject,), classdict)
        cls._patch(parent_lib)
        return cls


class NiceObject(with_metaclass(NiceObjectMeta, object)):
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


class LibMethod(object):
    def __init__(self, niceobj, libfunc):
        self._niceobj = niceobj
        self._libfunc = libfunc

        nh = niceobj._n_handles
        sig_str = '{}({}) -> {}'.format(libfunc.name, libfunc.sig.args_py_str(nh),
                                        libfunc.sig.rets_py_str())
        c_sig_str = '{}({})'.format(libfunc.c_name, libfunc.sig.args_c_str())
        self.__doc__ = sig_str + '\n\nOriginal C Function: ' + c_sig_str

        if sys.version_info >= (3,3):
            self._assign_signature()

    def _assign_signature(self):
        from inspect import Parameter, Signature
        params = [Parameter(h.c_argname, Parameter.POSITIONAL_OR_KEYWORD)
                  for h in self._libfunc.sig.in_handlers[self._niceobj._n_handles:]]
        self.__signature__ = Signature(params)

    def __call__(self, *args):
        return self._libfunc(*(self._niceobj._handles + args), niceobj=self._niceobj)


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
            with suppress(TypeError):
                return ffi.new(argtype, arg)

            with suppress(TypeError):
                return ffi.cast(argtype, arg)

        raise TypeError("A value castable to (or a valid initializer for) '{}' is required, "
                        "got '{}'".format(argtype, arg))
    else:
        return arg


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
            self.attrs = {n:(v if isinstance(v, Sig) else Sig.from_tuple(v))
                          for n,v in attrs.items()}

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
        log.info('Creating class %s...', clsname)
        flags = {
            'prefix': '',
            'struct_maker': None,  # ffi.new
            'buflen': 512,
            'use_numpy': False,
            'free_buf': None,
            'ret': ret_return,
        }
        classdict = {}
        niceobjectdefs = {}  # name: NiceObjectDef
        niceclasses = {}
        sigs = {}
        rethandlers = {}

        for name, value in orig_classdict.items():
            log.info("Processing attr '{}'...".format(name))
            if name in COMBINED_FLAGS:
                flags[name.strip('_')] = value

            elif isinstance(value, NiceObjectDef):
                if value.attrs is None:
                    value.names.remove(name)  # Remove self (context manager syntax)
                niceobjectdefs[name] = value

            elif isinstance(value, type) and issubclass(value, NiceObject):
                niceclasses[name] = value

            elif isinstance(value, RetHandler):
                rethandlers[name] = value

            elif isfunction(value):
                if hasattr(value, 'sig'):
                    sigs[name] = value.sig
                elif name.startswith('_ret_') and name != '_ret_':
                    # For backwards compatibility
                    rethandlers[name] = RetHandler(func=value, name=name[5:])
                else:
                    # Ordinary function (includes ret-handlers)
                    classdict[name] = staticmethod(value)

            elif isinstance(value, Sig):
                sigs[name] = value

            elif not name.startswith('_'):
                sigs[name] = Sig.from_tuple(value)

            else:
                classdict[name] = value

        log.info('Found NiceObjectDefs: %r', niceobjectdefs)
        log.info('Found NiceObject subclasses: %s', niceclasses)
        log.info('Found root sigs: %s', sigs)

        # Add these last to prevent user overwriting them
        classdict.update(_niceobjectdefs=niceobjectdefs, _niceclasses=niceclasses, _sigs=sigs,
                         _rethandlers=rethandlers, _base_flags=flags)
        log.info('classdict: %r', classdict)
        return super(LibMeta, metacls).__new__(metacls, clsname, bases, classdict)

    def __init__(cls, clsname, bases, classdict):
        cls._dir_ffilib = []  # Required by base class
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
        if '_err_wrap' in cls.__dict__:
            cls._base_flags['ret'] = cls._err_wrap
            del cls._err_wrap
            warnings.warn("Your class defines _err_wrap, which has been renamed to _ret, "
                          "please update your code:", stacklevel=2)

        if '_ret_wrap' in cls.__dict__:
            cls._base_flags['ret'] = cls._ret_wrap
            del cls._ret_wrap
            warnings.warn("Your class defines _ret_wrap, which has been renamed to _ret, "
                          "please update your code:", stacklevel=2)

    def _add_ret_handlers(cls):
        log.info('Adding return handlers...')
        ret_handlers = {}
        all_attrs = list(ChainMap(*(c.__dict__ for c in cls.mro())).items())
        for name, value in all_attrs:
            if isinstance(value, RetHandler):
                ret_handlers[name[5:]] = value
        cls._ret_handlers = ret_handlers  # Assign only after finding all _ret_-prefixed names
        log.info('ret_handlers: %s', cls._ret_handlers)

    def _handle_base_flags(cls):
        ret = cls._base_flags.get('ret')
        if isinstance(ret, basestring):
            cls._base_flags['ret'] = RetHandler(ret)

        if cls._ffi and not cls._base_flags['struct_maker']:
            cls._base_flags['struct_maker'] = cls._ffi.new

        # Add default empty prefix
        cls._base_flags['prefix'] = to_tuple(cls._base_flags['prefix'])
        if '' not in cls._base_flags['prefix']:
            cls._base_flags['prefix'] += ('',)

    def _add_dir_ffilib(cls):
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
        # Designed to be called by NiceLib and NiceObjectMeta
        prefixes = sig.flags.get('prefix', ())
        try:
            c_func, c_func_name = cls._find_c_func(shortname, prefixes)
        except ValueError:
            return None

        c_functype = cls._ffi.typeof(c_func)
        c_argtypes = c_functype.args
        if c_functype.ellipsis:
            c_argtypes = c_argtypes + ('...',)

        ret_handler = sig.flags['ret']
        if isinstance(ret_handler, basestring):
            ret_handler = cls._ret_handlers[ret_handler]

        if hasattr(cls, '_info'):
            arg_names = cls._info._argnames.get(c_func_name)
        else:
            arg_names = None

        sig.bind_argtypes(cls._ffi, shortname, c_argtypes, ret_handler, arg_names)

        return LibFunction(shortname, c_func_name, sig, c_func)

    def _find_c_func(cls, shortname, prefixes):
        for prefix in prefixes:
            func_name = prefix + shortname
            with suppress(AttributeError):
                return getattr(cls._ffilib, func_name), func_name

        raise ValueError("No lib function found with a name ending in '{}', with "
                         "any of these prefixes: {}".format(shortname, prefixes))

    def _create_niceobject_classes(cls):
        for niceobj_cls_name, niceobjdef in cls._niceobjectdefs.items():
            niceobj_cls = NiceObjectMeta.from_niceobjectdef(niceobj_cls_name, niceobjdef, cls)
            setattr(cls, niceobj_cls_name, niceobj_cls)

        for niceobj_cls_name, niceclass in cls._niceclasses.items():
            niceclass._patch(cls)
            setattr(cls, niceobj_cls_name, niceclass)

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
        log.debug("Getting attr '%s' from %s...", name, cls)
        try:
            return getattr(cls._ffilib, name)
        except Exception:
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


def unprefix(name, prefixes):
    for prefix in prefixes:
        if name.startswith(prefix):
            return prefix, name[len(prefix):]
    return '', name


class LibFunction(object):
    def __init__(self, name, c_name, sig, c_func):
        self.sig = sig
        self.name = name
        self.c_name = c_name
        self.c_func = c_func

        sig_str = '{}({}) -> {}'.format(name, sig.args_py_str(), sig.rets_py_str())
        c_sig_str = '{}({})'.format(c_name, sig.args_c_str())
        self.__doc__ = sig_str + '\n\nOriginal C Function: ' + c_sig_str

        if sys.version_info >= (3,3):
            self._assign_signature()

    def _assign_signature(self):
        from inspect import Parameter, Signature
        params = [Parameter(h.c_argname, Parameter.POSITIONAL_OR_KEYWORD)
                  for h in self.sig.in_handlers]
        self.__signature__ = Signature(params)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            return LibMethod(instance, self)

    def __call__(self, *args, **kwds):
        check_num_args(self.name, len(args), self.sig.num_inargs, self.sig.variadic)

        if len(args) != self.sig.num_inargs:
            raise TypeError("{}() takes {} arguments ({} given)"
                            "".format(self.name, self.sig.num_inargs, len(args)))

        ret_handler_args = {
            'niceobj': kwds.pop('niceobj', None),
            'funcname': self.name,
        }

        c_args = self.sig.make_c_args(args)
        retval = self.c_func(*c_args)
        return self.sig.extract_outputs(c_args, retval, ret_handler_args)


def check_num_args(func_name, num_args, num_req_args, is_variadic):
    message = None
    if is_variadic:
        if num_args < num_req_args - 1:
            message = '{}() takes at least '.format(func_name)
    else:
        if num_args != num_req_args:
            message = '{}() takes '.format(func_name)

    if message:
        if num_req_args == 0:
            message += 'no arguments'
        elif num_req_args == 1:
            message += '1 argument'
        else:
            message += '{} arguments'.format(num_req_args)

        message += ' ({} given)'.format(num_args)
        raise TypeError(message)


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

    @RetHandler(num_retvals=1)
    def _ret_return(retval):
        return retval

    @RetHandler(num_retvals=0)
    def _ret_ignore(retval):
        pass

    def __new__(cls):
        raise TypeError("Not allowed to instantiate {}. Use the class directly".format(cls))
