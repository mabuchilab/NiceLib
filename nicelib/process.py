# -*- coding: utf-8 -*-
# Copyright 2016-2017 Nate Bogdanowicz
from __future__ import unicode_literals, division, print_function
from future import standard_library
standard_library.install_aliases()
from builtins import str
from past.builtins import basestring
from future.utils import PY2

import re
import os.path
from io import open  # Needed for opening as unicode, might be slow on Python 2
import copy
import warnings
import logging as log
import pickle as pkl
from enum import Enum
from collections import OrderedDict, namedtuple, defaultdict, Sequence, deque
import ast
from io import StringIO
from pycparser import c_parser, c_generator, c_ast, plyparser
import cffi
import cffi.commontypes
from .platform import PREDEF_MACRO_STR, REPLACEMENT_MAP, INCLUDE_DIRS
from .util import handle_header_path

# Faster than using future's range function, speeds up lexer significantly
if PY2:
    range = xrange

cparser = c_parser.CParser()

TokenType = Enum('TokenType', 'DEFINED IDENTIFIER NUMBER STRING_CONST CHAR_CONST HEADER_NAME '
                 'PUNCTUATOR NEWLINE WHITESPACE LINE_COMMENT BLOCK_COMMENT')
Position = namedtuple('Position', ['row', 'col'])


# For converting from c_ast to Python ast
UNARY_OPS = {'-': ast.USub, '+': ast.UAdd, '!': ast.Not, '~': ast.Invert}
BINARY_OPS = {
    '+': ast.Add, '-': ast.Sub, '*': ast.Mult, '/': ast.Div, '%': ast.Mod, '<<': ast.LShift,
    '>>': ast.RShift, '|': ast.BitOr, '^': ast.BitXor, '&': ast.BitAnd
}
CMP_OPS = {'==': ast.Eq, '!=': ast.NotEq, '<': ast.Lt, '<=': ast.LtE, '>': ast.Gt, '>=': ast.GtE}
BOOL_OPS = {'&&': ast.And, '||': ast.Or}


# For converting from c_ast to Python source str
UNARY_OP_STR = {'+': '+', '-': '-', '!': ' not ', '~': '~'}
BINARY_OP_STR = {
    '+': '+', '-': '-', '*': '*', '/': '/', '<<': '<<', '>>': '>>', '|': '|', '^': '^', '&': '&'
}
CMP_OP_STR = {'==': '==', '!=': '!=', '<': '<', '<=': '<=', '>': '>', '>=': '>='}
BOOL_OP_STR = {'&&': ' and ', '||': ' or '}
ALL_BINOP_STRS = {}
ALL_BINOP_STRS.update(BINARY_OP_STR)
ALL_BINOP_STRS.update(CMP_OP_STR)
ALL_BINOP_STRS.update(BOOL_OP_STR)


UNOPS = {
    '+': lambda x: +x,
    '-': lambda x: -x,
    '!': lambda x: not x,
    '~': lambda x: ~x,
}
BINOPS = {
    '+': lambda x, y: x + y,
    '-': lambda x, y: x - y,
    '*': lambda x, y: x * y,
    '/': lambda x, y: x / y,
    '<<': lambda x, y: x << y,
    '>>': lambda x, y: x >> y,
    '|': lambda x, y: x | y,
    '&': lambda x, y: x & y,
    '^': lambda x, y: x ^ y,
    '==': lambda x, y: x == y,
    '!=': lambda x, y: x != y,
    '<': lambda x, y: x < y,
    '>': lambda x, y: x > y,
    '<=': lambda x, y: x <= y,
    '>=': lambda x, y: x >= y,
    '&&': lambda x, y: x and y,
    '||': lambda x, y: x or y,
}


class EndOfStreamError(Exception):
    pass


class LexError(Exception):
    pass


class ConvertError(Exception):
    pass


class PreprocessorError(Exception):
    def __init__(self, token, msg):
        msg = "[{}:{}:{}] {}".format(token.fpath, token.line, token.col, msg)
        super(PreprocessorError, self).__init__(msg)


class PreprocessorWarning(Warning):
    def __init__(self, token, msg):
        msg = "[{}:{}:{}] {}".format(token.fpath, token.line, token.col, msg)
        super(PreprocessorWarning, self).__init__(msg)


class ParseError(PreprocessorError):
    pass


class Token(object):
    def __init__(self, type, string, line=0, col=0, fpath='<string>', fname='<string>', from_sys_header=False):
        self.type = type
        self.string = string
        self.line = line
        self.col = col
        self.fpath = fpath
        self.fname = fname
        self.from_sys_header = from_sys_header

    def copy(self, from_sys_header=None):
        other = copy.copy(self)
        if from_sys_header is not None:
            other.from_sys_header = from_sys_header
        return other

    def matches(self, other_type, other_string):
        return self.type is other_type and self.string == other_string

    def __eq__(self, other):
        if isinstance(other, basestring):
            return self.string == other
        elif isinstance(other, TokenType):
            return self.type == other

        return self.string == other.string and self.type == other.type

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        string = '' if self.string == '\n' else self.string
        return '{}[{}:{}:{}]({})'.format(self.type.name, self.fname, self.line, self.col, string)

    def __repr__(self):
        return str(self)

for ttype in TokenType:
    setattr(Token, ttype.name, ttype)

NON_TOKENS = (Token.WHITESPACE, Token.NEWLINE, Token.LINE_COMMENT, Token.BLOCK_COMMENT)


class Lexer(object):
    def __init__(self):
        self.token_info = []
        self.ignored = []

    def add(self, name, regex_str, ignore=False, testfunc=None):
        self.token_info.append((name, re.compile(regex_str), testfunc))
        if ignore:
            self.ignored.append(name)

    def lex(self, text, fpath='<string>', is_sys_header=False):
        self.line = 1
        self.col = 1
        self.fpath = os.path.normcase(fpath)
        self.fname = os.path.basename(self.fpath[-17:])  # Do this once

        self.esc_newlines = defaultdict(int)
        self.is_sys_header = is_sys_header

        lines = text.splitlines()
        joined_lines = []
        continued_line = ''
        source_lineno = 1
        for line in lines:
            if line.endswith("\\"):
                continued_line = continued_line + line[:-1]
                self.esc_newlines[source_lineno] += 1
            else:
                joined_lines.append(continued_line + line)
                continued_line = ''
                source_lineno += 1 + self.esc_newlines.get(source_lineno, 0)
        text = '\n'.join(joined_lines)
        return lexer._lex_text(text)

    def _lex_text(self, text):
        self.tokens = []
        pos = 0
        while pos < len(text):
            token = self.read_token(text, pos)
            if token is None:
                raise LexError("({}:{}:{}) No acceptable token found!".format(self.line, self.col,
                                                                              self.fpath))
            if token.type not in self.ignored:
                self.tokens.append(token)
            pos = pos + len(token.string)

            for i in range(token.string.count('\n')):
                self.line += 1 + self.esc_newlines.get(self.line, 0)
                self.col = 1
            self.col += len(token.string.rsplit('\n', 1)[-1])

        return self.tokens

    def read_token(self, text, pos=0):
        """Read the next token from text, starting at pos"""
        best_token = None
        best_size = 0
        for token_type, regex, testfunc in self.token_info:
            match = regex.match(text, pos)
            if match:
                if testfunc and not testfunc(self.tokens):
                    continue

                size = match.end() - match.start()
                if size > best_size:
                    best_token = Token(token_type, match.group(0), self.line, self.col, self.fpath,
                                       self.fname, self.is_sys_header)
                    best_size = size
        return best_token


def _token_matcher_factory(match_strings, ignore_types=()):
    def matcher(tokens):
        match_iter = reversed(match_strings)
        test_string = next(match_iter)
        for token in reversed(tokens):
            if token.type in ignore_types:
                continue

            if token.string != test_string:
                return False

            try:
                test_string = next(match_iter)
            except StopIteration:
                return True  # Matched all of match_strings

        return False  # Did not get through all of match_strings
    return matcher


def build_c_lexer():
    # Only lex angle brackets as part of a header name immediately after `#include`
    include_matcher = _token_matcher_factory(
        ("#", "include"),
        ignore_types=(Token.NEWLINE, Token.WHITESPACE, Token.LINE_COMMENT, Token.BLOCK_COMMENT)
    )

    lexer = Lexer()
    lexer.add(Token.NEWLINE, r"\n", ignore=False)
    lexer.add(Token.WHITESPACE, r"[ \t\v\f]+", ignore=False)
    lexer.add(Token.NUMBER, r'\.?[0-9](?:[0-9$a-zA-Z_.]|(?:[eEpP][+-]))*')
    lexer.add(Token.DEFINED, r"defined")
    lexer.add(Token.IDENTIFIER, r"[$a-zA-Z_][$a-zA-Z0-9_]*")
    lexer.add(Token.STRING_CONST, r'"(?:[^"\\\n]|\\.)*"')
    lexer.add(Token.CHAR_CONST, r"'(?:[^'\\\n]|\\.)*'")
    lexer.add(Token.HEADER_NAME, r"<[^>\n]*>", testfunc=include_matcher)
    lexer.add(Token.LINE_COMMENT, r"//.*(?:$|(?=\n))", ignore=False)
    lexer.add(Token.BLOCK_COMMENT, r"/\*(?:.|\n)*?\*/", ignore=False)
    lexer.add(Token.PUNCTUATOR,
              r"[<>=*/*%&^|!+-]=|<<==|>>==|\.\.\.|->|\+\+|--|<<|>>|&&|[|]{2}|##|"
              r"[{}\[\]()<>.&*+-~!/%^|=;:,?#]")
    return lexer


lexer = build_c_lexer()


class Macro(object):
    def __init__(self, name_token, body):
        self.name = name_token.string
        self.line = name_token.line
        self.fpath = name_token.fpath
        self.col = name_token.col
        self.body = body
        self.py_src = None
        self.depends_on = ()

    @property
    def body(self):
        return self._body

    @body.setter
    def body(self, tokens):
        self._body = tokens
        self.depends_on = tuple(t.string for t in tokens if t.type is Token.IDENTIFIER)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return '<{}:{}:{}:{}>'.format(self.name, self.fpath, self.line, self.col)

    def body_str(self):
        return ' '.join(token.string for token in self.body)


class FuncMacro(Macro):
    def __init__(self, name_token, body, args, un_pythonable):
        super(FuncMacro, self).__init__(name_token, body)
        self.args = args
        self.un_pythonable = un_pythonable


class Parser(object):
    def __init__(self, source, fpath='', replacement_map=[], obj_macros=[], func_macros=[],
                 include_dirs=[], ignored_headers=(), ignore_system_headers=False):
        self.base_dir, self.fname = os.path.split(fpath)
        self.tokens = lexer.lex(source, fpath)
        self.replacement_map = replacement_map
        self.out = []
        self.cond_stack = []
        self.cond_done_stack = []
        self.include_dirs = include_dirs
        self.ignored_headers = tuple(os.path.normcase(p) for p in ignored_headers)
        self.ignore_system_headers = ignore_system_headers
        self.pragma_once = set()

        self.predef_obj_macros = {m.name: m for m in obj_macros}
        self.predef_func_macros = {m.name: m for m in func_macros}
        self.obj_macros = OrderedDict()
        self.func_macros = OrderedDict()

        self.expand_macros = True
        self.skipping = False
        self.output_defines = False
        self._ignored_tokens = (Token.NEWLINE, Token.WHITESPACE, Token.LINE_COMMENT,
                                Token.BLOCK_COMMENT)

        self.directive_parse_func = {
            'if': self.parse_if,
            'ifdef': self.parse_ifdef,
            'ifndef': self.parse_ifndef,
            'else': self.parse_else,
            'elif': self.parse_elif,
            'endif': self.parse_endif,
            'define': self.parse_define,
            'undef': self.parse_undef,
            'pragma': self.parse_pragma,
            'include': self.parse_include,
            'error': self.parse_error,
            'warning': self.parse_warning,
        }

    def obj_macro_defined(self, name):
        return (name in self.obj_macros) or (name in self.predef_obj_macros)

    def func_macro_defined(self, name):
        return (name in self.func_macros) or (name in self.predef_func_macros)

    def any_macro_defined(self, name):
        return any(name in d.keys() for d in (self.obj_macros, self.func_macros,
                                              self.predef_obj_macros, self.predef_func_macros))

    def get_obj_macro(self, name, default=None):
        if name in self.obj_macros:
            return self.obj_macros[name]
        elif name in self.predef_obj_macros:
            return self.predef_obj_macros[name]
        return default

    def get_func_macro(self, name, default=None):
        if name in self.func_macros:
            return self.func_macros[name]
        elif name in self.predef_func_macros:
            return self.predef_func_macros[name]
        return default

    def get_any_macro(self, name, default=None):
        for macros in (self.obj_macros, self.func_macros, self.predef_obj_macros,
                       self.predef_func_macros):
            if name in macros:
                return macros[name]
        return default

    def add_obj_macro(self, macro):
        self.obj_macros[macro.name] = macro

    def add_func_macro(self, macro):
        self.func_macros[macro.name] = macro

    def undef_macro(self, name):
        if name in self.obj_macros:
            del self.obj_macros[name]
        elif name in self.func_macros:
            del self.func_macros[name]
        else:
            log.debug("#undef of nonexistent macro '{}'".format(name))

    def ordered_macro_items(self):
        all_items = list(self.obj_macros.items()) + list(self.func_macros.items())
        return sorted(all_items, key=(lambda tup: (tup[1].line, tup[1].col)))

    def pop(self, test_type=None, test_string=None, dont_ignore=(), silent=False):
        return self._pop_base(self.tokens, test_type, test_string, dont_ignore, silent,
                              track_lines=True)

    def pop_from(self, tokens, test_type=None, test_string=None, dont_ignore=()):
        return self._pop_base(tokens, test_type, test_string, dont_ignore, silent=True,
                              track_lines=False)

    def _log_token(self, token):
        log.debug("{}Popped token {}".format('[skipping]' if self.skipping else '', token))

    def _pop_base(self, tokens, test_type=None, test_string=None, dont_ignore=(), silent=True,
                  track_lines=False):
        while True:
            try:
                token = tokens.pop(0)
                if track_lines:
                    self._log_token(token)
            except IndexError:
                raise EndOfStreamError

            if not silent and not self.skipping:
                self.out_line.append(token)

            if (token.type in dont_ignore) or (token.type not in self._ignored_tokens):
                break

        if test_type is not None and token.type != test_type:
            raise ParseError(token, "Expected token type {}, got {}".format(test_type, token.type))

        if test_string is not None and token.string != test_string:
            raise ParseError(token, "Expected token string '{}', got '{}'".format(test_string,
                                                                                  token.string))

        return token

    def parse(self, update_cb=None):
        while True:
            try:
                self.parse_next()
            except EndOfStreamError:
                break

            if update_cb and self.out:
                update_cb(self.out[-1].line)

        self.macros = [macro for (name, macro) in self.ordered_macro_items()]

    def parse_next(self):
        self.out_line = []
        token = self.pop(dont_ignore=(Token.NEWLINE,))

        if token.type is Token.NEWLINE:
            if not self.skipping:
                self.out.extend(self.out_line)
        elif token.matches(Token.PUNCTUATOR, '#'):
            dir_token = self.pop()
            log.debug("Parsing directive")
            parse_directive = self.directive_parse_func.get(dir_token.string)

            if parse_directive is not None:
                keep_line = parse_directive()
            elif self.skipping:
                self.pop_until_newline()  # Unrecog
                keep_line = False
            else:
                raise ParseError(dir_token, "Unrecognized directive #{}".format(dir_token.string))

            if keep_line:
                self.out.extend(self.out_line)
        else:
            # Grab tokens until we get to a line with a '#'
            last_newline_idx = 0
            for i, t in enumerate(self.tokens):
                if t.type is Token.NEWLINE:
                    last_newline_idx = i
                elif t.string == '#':
                    break

            for t in self.tokens[:last_newline_idx]:
                self._log_token(t)

            # Add to output
            if not self.skipping:
                expanded = self.macro_expand([token] + self.tokens[:last_newline_idx])
                for token in expanded:
                    self.out.append(token)
                    self.perform_replacement()

            self.tokens = self.tokens[last_newline_idx:]

    def append_to_output(self, token):
        if not self.skipping:
            self.out.append(token)
            self.perform_replacement()

    def perform_replacement(self):
        for test_strings, repl_string in self.replacement_map:
            try:
                match = True
                i = 1
                for test_string in reversed(test_strings):
                    token = self.out[-i]
                    while token.type in (Token.WHITESPACE, Token.NEWLINE, Token.BLOCK_COMMENT,
                                         Token.LINE_COMMENT):
                        i += 1
                        token = self.out[-i]

                    if test_string != self.out[-i].string:
                        match = False
                        break
                    i += 1
            except IndexError:
                match = False

            if match:
                fpath = self.out[-1].fpath
                for _ in range(i - 1):
                    self.out.pop(-1)
                repl_tokens = lexer.lex(repl_string, fpath)
                self.out.extend(repl_tokens)
                break  # Only allow a single replacement

    def parse_macro(self):
        token = self.pop()
        return self.get_obj_macro(token.string, None)

    def start_if_clause(self, condition):
        self.cond_stack.append(condition)
        self.cond_done_stack.append(condition)
        self.skipping = not all(self.cond_stack)

    def start_else_clause(self):
        cond_done = self.cond_done_stack[-1]
        self.cond_stack[-1] = not cond_done
        self.cond_done_stack[-1] = True
        self.skipping = not all(self.cond_stack)

    def start_elif_clause(self, elif_cond):
        cond_done = self.cond_done_stack[-1]
        self.cond_stack[-1] = (not cond_done) and elif_cond
        self.cond_done_stack[-1] = cond_done or elif_cond
        self.skipping = not all(self.cond_stack)

    def end_if_clause(self):
        self.cond_stack.pop(-1)
        self.cond_done_stack.pop(-1)
        self.skipping = not all(self.cond_stack)

    def assert_line_empty(self):
        """Pops all tokens up to a newline (or end of stream) and asserts that they're empty
        (either NEWLINE, WHITESPACE, LINE_COMMENT, or BLOCK_COMMENT)
        """
        while True:
            try:
                token = self.pop(dont_ignore=(Token.NEWLINE,))
            except EndOfStreamError:  # End of token stream
                break

            if token.type is Token.NEWLINE:
                break

            if token.type not in (Token.WHITESPACE, Token.LINE_COMMENT, Token.BLOCK_COMMENT):
                raise ParseError(token, "Rest of line should be devoid of any tokens!")

    def pop_until_newline(self, dont_ignore=(), silent=False):
        """Pops all tokens up to a newline (or end of stream) and returns them"""
        tokens = []
        while True:
            try:
                token = self.pop(dont_ignore=(Token.NEWLINE,) + dont_ignore, silent=silent)
            except EndOfStreamError:  # End of token stream
                break

            if token.type is Token.NEWLINE:
                break
            tokens.append(token)
        return tokens

    def parse_if(self):
        if self.skipping:
            self.pop_until_newline
            self.start_if_clause(False)
        else:
            value = self.parse_expression(self.pop_until_newline())
            self.start_if_clause(bool(value))
        return False

    def macro_expand(self, tokens, blacklist=[], func_blacklist=[]):
        if tokens:
            tokens = tokens[:]  # Copy so we can pop
            token = tokens.pop(0)
        else:
            return []

        expanded = []
        done = False

        while not done:
            if token.type is Token.IDENTIFIER:
                done = True
                spaces = []
                while tokens:
                    next_token = tokens.pop(0)
                    if next_token.type is Token.WHITESPACE:
                        spaces.append(next_token)
                    else:
                        done = False
                        break

                if (not done and next_token.string == '(' and
                        self.func_macro_defined(token.string) and
                        token.string not in func_blacklist):
                    # Func-like macro
                    # Pop tokens until the closing paren
                    name_token = token
                    name = token.string
                    macro = self.get_func_macro(name)
                    arg_lists = [[]]
                    n_parens = 1
                    while n_parens > 0:
                        token = tokens.pop(0)
                        if token.string == '(':
                            n_parens += 1
                        elif token.string == ')':
                            n_parens -= 1

                        if token.string == ',' and n_parens == 1:
                            arg_lists.append([])
                        elif n_parens > 0:
                            arg_lists[-1].append(token)

                    if len(macro.args) != len(arg_lists):
                        raise ParseError(name_token, "Func-like macro '{}' needs {} arguments, got "
                                         "{}".format(name, len(macro.args), len(arg_lists)))

                    # Expand args
                    exp_arg_lists = [self.macro_expand(a, blacklist, func_blacklist + [name]) for
                                     a in arg_lists]

                    # Substitute args into body, then expand it
                    expanded_body = self.macro_expand_funclike_body(
                        macro, exp_arg_lists, in_sys_header=name_token.from_sys_header
                    )
                    expanded.extend(expanded_body)

                    if tokens:
                        token = tokens.pop(0)
                    else:
                        done = True
                else:
                    if self.obj_macro_defined(token.string) and token.string not in blacklist:
                        # Object-like macro expand
                        body = self.get_obj_macro(token.string).body
                        copied_body = [t.copy(from_sys_header=token.from_sys_header) for t in body]
                        expanded_body = self.macro_expand(copied_body, blacklist + [token.string],
                                                          func_blacklist)
                        expanded.extend(expanded_body)

                    else:
                        # Ordinary identifier
                        expanded.append(token)
                    expanded.extend(spaces)

                    if not done:
                        token = next_token
            else:
                # Ordinary token
                expanded.append(token)
                if tokens:
                    token = tokens.pop(0)
                else:
                    done = True
        return expanded

    def macro_expand_funclike_body(self, macro, exp_arg_lists, blacklist=[], func_blacklist=[],
                                   in_sys_header=False):
        body = []
        last_real_token = None
        last_real_token_idx = -1
        concatting = False

        # Sub in args in first pass
        substituted = []
        for token in macro.body:
            if token.type is Token.IDENTIFIER and token.string in macro.args:
                arg_idx = macro.args.index(token.string)
                substituted.extend(exp_arg_lists[arg_idx])
            else:
                substituted.append(token.copy(from_sys_header=in_sys_header))

        # Do concatting pass
        for token in substituted:
            if concatting:
                if token.type not in NON_TOKENS:
                    concat_str = last_real_token.string + token.string
                    log.debug("Macro concat produced '{}'".format(concat_str))
                    lexer.is_sys_header = in_sys_header
                    new_token = lexer.read_token(concat_str, pos=0)
                    body.append(new_token)
                    concatting = False
                continue

            if token.string == '##':
                log.debug("Saw ##")
                body = body[:last_real_token_idx]
                concatting = True
                last_real_token_idx = -1
            else:
                body.append(token)
                if token.type not in NON_TOKENS:
                    last_real_token = token
                    last_real_token_idx = len(body) - 1

        # Expand body and return
        return self.macro_expand(body, blacklist, func_blacklist + [macro.name])

    def parse_expression(self, tokens):
        tokens = tokens[:]
        expanded = []
        while tokens:
            token = self.pop_from(tokens)
            if token.type is Token.DEFINED:
                token = self.pop_from(tokens)
                if token.string == '(':
                    token = self.pop_from(tokens, Token.IDENTIFIER)
                    self.pop_from(tokens, Token.PUNCTUATOR, ')')
                elif token.type != Token.IDENTIFIER:
                    raise ParseError(token, "Need either '(' or identifier after `defined`")
                val = '1' if self.any_macro_defined(token.string) else '0'
                expanded.append(Token(Token.NUMBER, val))
            else:
                expanded.append(token)

        exp = self.macro_expand(expanded)
        tokens = []
        for token in exp:
            if token.type is Token.IDENTIFIER:
                log.debug(PreprocessorWarning(token, "Unidentified identifier {} in expression"
                                                     ", treating as 0...".format(token.string)))
                tokens.append(Token(Token.NUMBER, '0'))
            else:
                tokens.append(token)

        py_src = c_to_py_src(' '.join(token.string for token in tokens))
        log.debug("py_src = '{}'".format(py_src))
        return eval(py_src, {})

    def parse_ifdef(self):
        if self.skipping:
            self.pop_until_newline()
            self.start_if_clause(False)
        else:
            macro = self.parse_macro()
            self.start_if_clause(macro is not None)
            self.assert_line_empty()
        return False

    def parse_ifndef(self):
        if self.skipping:
            self.pop_until_newline()
            self.start_if_clause(False)
        else:
            macro = self.parse_macro()
            self.start_if_clause(macro is None)
            self.assert_line_empty()
        return False

    def parse_else(self):
        if not all(self.cond_stack[:-1]):  # if outer scope is skipping
            self.pop_until_newline()
            self.start_else_clause()
        else:
            self.start_else_clause()
            self.assert_line_empty()
        return False

    def parse_elif(self):
        if not all(self.cond_stack[:-1]):  # if outer scope is skipping
            self.pop_until_newline()
            self.start_elif_clause(False)
        else:
            value = self.parse_expression(self.pop_until_newline())
            self.start_elif_clause(bool(value))
        return False

    def parse_endif(self):
        self.end_if_clause()
        self.pop_until_newline()  # Apparently the line doesn't need to be empty...
        return False

    def parse_define(self):
        name_token = self.pop(Token.IDENTIFIER)

        # The VERY NEXT token (including whitespace) must be a paren
        if self.tokens[0].matches(Token.PUNCTUATOR, '('):
            # Func-like macro
            # Param-list is identifiers, separated by commas and optional whitespace
            self.pop()  # '('
            args = []
            needs_comma = False
            while True:
                token = self.pop()
                if token.matches(Token.PUNCTUATOR, ')'):
                    break

                if needs_comma:
                    if token.matches(Token.PUNCTUATOR, ','):
                        needs_comma = False
                    else:
                        raise ParseError(token, "Need comma in arg list")
                elif token.type is Token.IDENTIFIER:
                    args.append(token.string)
                    needs_comma = True
                elif token == '...':
                    args.append(token.string)
                else:
                    raise ParseError(token, "Invalid token {} in arg list".format(token))

            dont_ignore = (Token.WHITESPACE, Token.BLOCK_COMMENT, Token.LINE_COMMENT)
            tokens = self.pop_until_newline(silent=True, dont_ignore=dont_ignore)

            un_pythonable = False
            for token in tokens:
                if token.string == '##':
                    un_pythonable = True

            if not self.skipping:
                preamble, body, postamble = self._split_body(tokens)
                macro = FuncMacro(name_token, body, args, un_pythonable)
                self.add_func_macro(macro)
                log.debug("Saving func-macro {} = {}".format(macro, body))
        else:
            # Object-like macro
            dont_ignore = (Token.WHITESPACE, Token.BLOCK_COMMENT, Token.LINE_COMMENT)
            tokens = self.pop_until_newline(silent=True, dont_ignore=dont_ignore)

            if not self.skipping:
                preamble, body, postamble = self._split_body(tokens)
                macro = Macro(name_token, body)
                self.add_obj_macro(macro)
                log.debug("Saving obj-macro {} = {}".format(macro, body))

        # Output all the tokens we suppressed
        self.out_line.extend(tokens)
        self.out_line.append(Token(Token.NEWLINE, '\n'))
        return self.output_defines

    @staticmethod
    def _split_body(tokens):
        preamble, postamble = [], []
        for token in tokens:
            if token.type in (Token.WHITESPACE, Token.BLOCK_COMMENT, Token.LINE_COMMENT):
                preamble.append(token)
            else:
                break

        for token in reversed(tokens):
            if token.type in (Token.WHITESPACE, Token.BLOCK_COMMENT, Token.LINE_COMMENT):
                postamble.insert(0, token)
            else:
                break

        start = len(preamble)
        if start == len(tokens):
            postamble = []
        stop = len(tokens) - len(postamble)

        return preamble, tokens[start:stop], postamble

    def parse_undef(self):
        name_token = self.pop(Token.IDENTIFIER)
        self.assert_line_empty()

        if not self.skipping:
            try:
                self.undef_macro(name_token.string)
            except KeyError:
                pass
        return False

    def parse_pragma(self):
        tokens = self.pop_until_newline()

        if len(tokens) == 1 and tokens[0] == 'once':
            self.pragma_once.add(tokens[0].fpath)

        return False

    def parse_error(self):
        tokens = self.pop_until_newline()
        if not self.skipping:
            log.debug("obj_macros = {}".format(self.obj_macros))
            log.debug("func_macros = {}".format(self.func_macros))
            message = ''.join(token.string for token in tokens)
            raise PreprocessorError(tokens[0], message)
        return False

    def parse_warning(self):
        tokens = self.pop_until_newline()
        if not self.skipping:
            message = ''.join(token.string for token in tokens)
            warnings.warn(PreprocessorWarning(tokens[0], message))
        return False

    def parse_include(self):
        tokens = self.pop_until_newline()  # Ignore includes
        if self.skipping:
            return False

        if len(tokens) != 1 or tokens[0].type not in (Token.HEADER_NAME, Token.STRING_CONST):
            raise ParseError(self.out_line[-1], "Invalid #include line")
        token = tokens[0]
        hpath = token.string[1:-1]
        base_dir = os.path.split(token.fpath)[0]

        if os.path.normcase(hpath) in self.ignored_headers:
            log.debug("Explicitly ignored header '{}'".format(hpath))
            return False

        def search_for_file(dirs, relpath):
            if os.path.isabs(relpath):
                if os.path.exists(relpath):
                    return relpath
                else:
                    return None

            for try_dir in dirs:
                try_path = os.path.join(try_dir, relpath)
                if os.path.exists(try_path):
                    return try_path
            return None

        if token.type is Token.HEADER_NAME:
            if self.ignore_system_headers:
                log.debug("Ignoring system header {}".format(hpath))
                return False

            log.debug("System header {}".format(hpath))
            # We include the local path too, which is not standard
            dirs = self.include_dirs + [base_dir]
            path = search_for_file(dirs, hpath)
            is_sys_header = True

            if not path:
                raise PreprocessorError(token, 'System header "{}" not found'.format(hpath))
        else:
            log.debug("Local header {}".format(hpath))
            dirs = [base_dir] + self.include_dirs
            path = search_for_file(dirs, hpath)
            is_sys_header = False

            if not path:
                raise PreprocessorError(token, 'Program header "{}" not found'.format(hpath))

        path = os.path.normcase(path)
        if path in self.pragma_once:
            log.debug("Skipping header due to '#pragma once'")
            return False

        log.debug("Including header {!r}".format(path))
        with open(path, 'rU') as f:
            tokens = lexer.lex(f.read(), path, is_sys_header=is_sys_header)
            tokens.append(Token(Token.NEWLINE, '\n'))

        # Prepend this header's tokens
        self.tokens = tokens + self.tokens
        return False


class TreeModifier(c_ast.NodeVisitor):
    """A special type of visitor class that modifies an AST in place

    Subclass this and implement the various `visit_X` methods which transform nodes of each type.
    You can then instantiate the class and use it to implement an AST hook.

    Its `visit_X` methods must return a value, which correspond to the transformed node. If the node
    is contained in a parent node's list and its `visit_X` method returns None, it will be removed
    from the list. This modification/removal is implemented via `generic_visit`, so you can override
    it on a per-nodetype basis.

    The `X` in `visit_X` is the node type's name, e.g. `visit_Enum`. See ``pycparser.c_ast`` or
    ``pycparser._c_ast.cfg`` for all the available types of nodes, and
    ``pycparser.c_ast.NodeVisitor`` to see the base visitor class.
    """
    def visit(self, node):
        method = 'visit_' + node.__class__.__name__
        return getattr(self, method, self.generic_visit)(node)

    def generic_visit(self, node):
        lists = defaultdict(list)
        for child_name, child in node.children():
            result = self.visit(child)
            if '[' in child_name:
                attr_name, rest = child_name.split('[')
                idx = int(rest[:-1])
                lists[attr_name].insert(idx, result)
            else:
                setattr(node, child_name, result)

        for attr_name, node_list in lists.items():
            node_list = [n for n in node_list if n is not None]
            setattr(node, attr_name, node_list)

        return node


class FFICleaner(TreeModifier):
    """A visitor class for cleaning up `c_ast`s

    One major feature is that this will evaluate numeric expressions and replace them with
    constants. This allows arrays with calculated lengths to be used by cffi. In general we want to
    support use of `sizeof` as well, so we need to have ffi parse each typedef as we see it so we
    know the available sizes.

    This also cleans up a tricky issue where pycparser will split a multi-element typedef into
    multiple typedefs, possible duplicating a struct/union/enum definition. Here we are careful to
    erase all but the first definition.

    All function definitions are also removed.
    """
    def __init__(self, ffi):
        self.ffi = ffi
        self.generator = c_generator.CGenerator()
        self.defined_tags = set()
        self.cur_typedef_name = None
        self.id_vals = {}  # Ordinary C identifiers (use just for enum values)
        self.cur_enum_val = 0

    def visit_Typedef(self, node):
        # Visit typedecl hierarchy first
        tmp_name = self.cur_typedef_name
        self.cur_typedef_name = node.name
        self.visit(node.type)
        self.cur_typedef_name = tmp_name

        # Now add type to FFI
        src = self.generator.visit(node) + ';'
        log.debug(src)
        try:
            self.ffi.cdef(src, override=True)
        except cffi.api.FFIError as e:
            log.error(str(e))  # Ignore bad or unsupported types
        return node

    def visit_Enum(self, node):
        if not node.name and self.cur_typedef_name:
            node.name = '__autotag_' + self.cur_typedef_name

        if node.values:  # Is a definition
            self.cur_enum_val = 0  # Reset per enum definition
            if node.name is None:
                self.generic_visit(node)
            elif node.name in self.defined_tags:
                node = c_ast.Enum(node.name, ())
            else:
                self.defined_tags.add(node.name)
                self.generic_visit(node)
        return node

    def visit_StructOrUnion(self, node, node_class):
        if not node.name and self.cur_typedef_name:
            node.name = '__autotag_' + self.cur_typedef_name

        if node.decls:  # Is a definition
            if node.name is None:
                self.generic_visit(node)
            elif node.name in self.defined_tags:
                node = node_class(node.name, ())
            else:
                self.defined_tags.add(node.name)
                self.generic_visit(node)
        return node

    def visit_Struct(self, node):
        return self.visit_StructOrUnion(node, c_ast.Struct)

    def visit_Union(self, node):
        return self.visit_StructOrUnion(node, c_ast.Union)

    def visit_FuncDef(self, node):
        return None

    def visit_ArrayDecl(self, node):
        node.type = self.visit(node.type)
        if node.dim is not None:
            node.dim = self.visit(node.dim)
        return node

    def visit_Enumerator(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
            py_value = self._val_from_const(node.value)
        else:
            py_value = self.cur_enum_val

        self.cur_enum_val = py_value + 1
        self.id_vals[node.name] = py_value

        return node

    def _val_from_id(self, id):
        try:
            return self.id_vals[id.name]
        except KeyError:
            raise ConvertError("Unknown identifier '{}'".format(id.name))

    def _val_from_const(self, const):
        """Gets the python numeric value of a c_ast Constant (or ID)"""
        assert isinstance(const, (c_ast.Constant, c_ast.ID))
        if isinstance(const, c_ast.ID):
            return self._val_from_id(const)

        if const.type == 'int':
            int_str = const.value.lower().rstrip('ul')
            if int_str.startswith('0x'):
                base = 16
            elif int_str.startswith('0b'):
                base = 2
            elif int_str.startswith('0'):
                base = 8
            else:
                base = 10
            return int(int_str, base)
        elif const.type == 'float':
            return float(const.value.rstrip('FfLl'))
        elif const.type == 'string':
            return const.value
        else:
            raise ConvertError("Unknown constant type '{}'".format(const.type))

    @staticmethod
    def _const_from_val(val):
        if isinstance(val, int):
            return c_ast.Constant('int', str(int(val)))
        elif isinstance(val, float):
            return c_ast.Constant('float', str(val))
        elif isinstance(val, str):
            return c_ast.Constant('string', val)
        else:
            raise ConvertError("Unknown value type '{}'".format(val))

    def visit_UnaryOp(self, node):
        if node.op == 'sizeof':
            type_str = self.generator.visit(node.expr)
            log.debug("SIZEOF({})".format(type_str))
            val = self.ffi.sizeof(type_str)
        elif node.op in UNOPS:
            expr_val = self._val_from_const(self.visit(node.expr))
            val = UNOPS[node.op](expr_val)
        else:
            raise ConvertError("Unknown unary op '{}'".format(node.op))
        return self._const_from_val(val)

    def visit_TernaryOp(self, node):
        return self.visit(node.iftrue if node.cond else node.iffalse)

    def visit_BinaryOp(self, node):
        left_val = self._val_from_const(self.visit(node.left))
        right_val = self._val_from_const(self.visit(node.right))
        if node.op == '/':
            if isinstance(left_val, int) and isinstance(right_val, int):
                val = left_val // right_val
            else:
                val = left_val / right_val
        elif node.op in BINOPS:
            val = BINOPS[node.op](left_val, right_val)
        else:
            raise ConvertError("Unknown binary op '{}'".format(node.op))

        return self._const_from_val(val)

    def visit_Cast(self, node):
        # TODO: Use FFI to cast?
        if not isinstance(node.to_type.type, c_ast.TypeDecl):
            raise ConvertError("Unsupported cast type {}".format(node.to_type.type))
        type_str = ' '.join(node.to_type.type.type.names)
        py_type = float if ('float' in type_str or 'double' in type_str) else int
        return self._const_from_val(py_type(self._val_from_const(self.visit(node.expr))))

    def visit_Decl(self, node):
        # Undo stdcall hack
        if node.quals[-3:] == ['volatile', 'volatile', 'const']:
            node.quals = node.quals[:-3] + ['__stdcall']
        return self.generic_visit(node)

    def visit_FuncDecl(self, node):
        # Undo stdcall hack
        if node.type.quals[-3:] == ['volatile', 'volatile', 'const']:
            node.type.quals = node.type.quals[:-3] + ['__stdcall']
        return self.generic_visit(node)


class Generator(object):
    def __init__(self, tokens, macros, macro_expand, token_hooks=(), string_hooks=(), ast_hooks=(),
                 debug_file=None):
        self.tokens = tokens
        self.macros = macros
        self.expander = macro_expand

        self.token_hooks = token_hooks
        self.string_hooks = string_hooks
        self.ast_hooks = ast_hooks

        self.debug_file = debug_file
        self.parser = cparser
        self.tree = self.parser.parse('')

    @staticmethod
    def common_type_names(tokens, type_names):
        """Get a list of common type names that haven't been typedef'd in the source.

        Uses the approach taken from that of cffi's `_common_type_names()`
        """
        useful_tokens = set(type_names)
        useful_tokens.update(';,()[]{}')
        useful_tokens.add('typedef')
        names_used = set()

        in_typedef = False
        prev_token = None
        depth = 0
        for token in tokens:
            if token.string in useful_tokens:
                if token in ('(', '{', '['):
                    depth += 1
                elif token in (')', '}', ']'):
                    depth -= 1
                elif token == 'typedef':
                    in_typedef = True
                elif token == ';':
                    if in_typedef and depth == 0:
                        names_used.discard(prev_token.string)
                        useful_tokens.discard(prev_token.string)
                        in_typedef = False
                elif token == ',':
                    if in_typedef and depth == 0:
                        names_used.discard(prev_token.string)
                        useful_tokens.discard(prev_token.string)
                else:
                    names_used.add(token.string)

            if token not in NON_TOKENS:
                prev_token = token
        return names_used

    def generate(self):
        # HOOK: list of tokens
        log.debug("Applying token hooks")
        self.token_hooks += (stdcall_hook, cdecl_hook, add_line_directive_hook)  # Add builtin hooks
        tokens = self.tokens

        for hook in self.token_hooks:
            log.debug("Applying hook '{}'".format(hook.__name__))
            tokens = hook(tokens)

        # Generate parseable chunks
        def get_ext_chunks(chunk_tokens):
            """Generates a sequence of (chunk_str, from_sys_header) pairs"""
            chunk = []
            depth = 0
            from_sys_header = None

            for tok_num, token in enumerate(chunk_tokens):
                if from_sys_header is None and not token.fname.startswith('<'):
                    from_sys_header = token.from_sys_header

                if token in ('{', '(', '['):
                    depth += 1
                elif token in ('}', ')', ']'):
                    depth -= 1

                chunk.append(token.string)

                if depth == 0 and token == ';':
                    yield ''.join(chunk), from_sys_header, tok_num + 1
                    chunk = []
                    from_sys_header = None

            # Yield unfinished final chunk
            if chunk:
                yield ''.join(chunk), from_sys_header, tok_num + 1

        # Log intermediate c-source
        if self.debug_file:
            with open(self.debug_file, 'w') as f:
                f.write(''.join(t.string for t in tokens))

        # pycparser doesn't know about these types by default, but cffi does. We just need to make
        # sure that pycparser knows these are types, the particular type is unimportant
        common_types = self.common_type_names(tokens, cffi.commontypes.COMMON_TYPES.keys())
        fake_types = '\n'.join('typedef int {};'.format(t) for t in common_types)
        self.parse(fake_types)

        log.debug("Parsing chunks")
        chunk_start_tok_num = 0
        for csource_chunk, from_sys_header, next_tok_num in get_ext_chunks(tokens):
            orig_chunk = csource_chunk
            csource_chunk = csource_chunk.replace('\f', ' ')

            log.debug("Parsing chunk '{}'".format(csource_chunk))
            try:
                chunk_tree = self.parse(csource_chunk)
            except plyparser.ParseError as e:
                msg = str(e)
                lines = orig_chunk.splitlines()
                if len(lines) < 20:
                    msg += '\nWhen parsing chunk:\n<<<{}\n>>>'.format(orig_chunk)
                else:
                    msg += ('\nWhen parsing chunk:\n<<<{}\n\n(...)\n\n{}'
                            '>>>'.format('\n'.join(lines[:10]), '\n'.join(lines[-10:])))

                msg += ('\n\nIf you a developer wrapping a lib, you may need to clean up the '
                        'header source using hooks. See the documentation on processing headers '
                        'for more information.')
                raise plyparser.ParseError(msg)

            # HOOK: AST chunk
            for hook in self.ast_hooks:
                chunk_tree = hook(chunk_tree, self.parse)

            # Skip adding func decls from system header files
            if chunk_tree.ext:
                ext = chunk_tree.ext[0]
                if (not isinstance(ext, c_ast.Decl) or not isinstance(ext.type, c_ast.FuncDecl) or
                        not from_sys_header):
                    self.tree.ext.extend(chunk_tree.ext)

            chunk_start_tok_num = next_tok_num
            log.debug("Parsed to token {}/{}".format(next_tok_num-1, len(tokens)))

        log.debug("pycparser successfully re-parsed cleaned header")

        # Remove function defs and replace 'volatile volatile const'
        ffi = cffi.FFI()
        cleaner = FFICleaner(ffi)
        self.tree = cleaner.visit(self.tree)

        # Generate cleaned C source
        generator = c_generator.CGenerator()
        header_src = generator.visit(self.tree)

        # Convert macros
        macro_src = StringIO()
        macro_src.write("# Generated macro definitions\n")
        macro_src.write("defs = {}\n")

        for macro in self.macros:
            py_src = self.gen_py_src(macro)
            if py_src:
                dependencies_satisfied = True
                for macro_name in macro.depends_on:
                    if not self.obj_macro_defined(macro_name):
                        dependencies_satisfied = False

                if not dependencies_satisfied:
                    macro_src.write("# ")

                if isinstance(macro, FuncMacro):
                    arg_list = ', '.join(macro.args)
                    macro_src.write("defs['{}'] = lambda {}: {}\n".format(macro.name, arg_list,
                                                                          py_src))
                else:
                    macro_src.write("defs['{}'] = {}\n".format(macro.name, py_src))

        return header_src, macro_src.getvalue(), self.tree

    def gen_py_src(self, macro):
        if isinstance(macro, FuncMacro):
            prefix = '__FMACRO_'
            args = macro.args
        else:
            prefix = '__OMACRO_'
            args = ()

        log.debug("Generating body of macro {} "
                 "[{}:{}:{}]".format(macro.name, macro.fpath, macro.line, macro.col))
        log.debug("  body tokens are {}".format(macro.body))

        py_src = None
        if macro.body:
            expanded = self.expander(macro.body)
            for token in expanded:
                if token.type is Token.IDENTIFIER and token.string not in args:
                    log.debug("Identifier '{}' still in the macro body after expansion, ignoring "
                              "this macro definition".format(token.string))
                    return None
            c_src = ''.join(token.string for token in expanded)
            func_src = "\nint " + prefix + macro.name + "(void){" + c_src + ";}"

            try:
                tree = self.parse(func_src, reset_file=True)
                expr_node = tree.ext[0].body.block_items[0]
                try:
                    py_src = ''.join(to_py_src(expr_node))
                except ConvertError as e:
                    warnings.warn(str(e))

            except (plyparser.ParseError, AttributeError) as e:
                warnings.warn("Un-pythonable macro {}".format(macro.name))
                warnings.warn(str(e))

        log.debug("  generated to {}".format(py_src))
        return py_src

    def parse(self, text, reset_file=False):
        """Reimplement CParser.parse to retain scope"""
        if reset_file:
            self.parser.clex.filename = '<generator>'
            self.parser.clex.reset_lineno()
        #self.parser._scope_stack = [dict()]
        self.parser._last_yielded_token = None
        return self.parser.cparser.parse(input=text, lexer=self.parser.clex, debug=0)


def get_predef_macros():
    parser = Parser(PREDEF_MACRO_STR, '<predef>')
    parser.parse()
    return parser.macros, parser.func_macros


def write_tokens_simple(file, parser):
    for token in parser.out:
        file.write(token.string)


def write_tokens(file, parser, add_newlines=True):
    needs_space = False
    accept_newline = False
    for token in parser.out:
        if token.type is Token.NEWLINE:
            if accept_newline:
                file.write('\n')
                needs_space = False
            accept_newline = False
        elif token.type not in (Token.WHITESPACE, Token.LINE_COMMENT, Token.BLOCK_COMMENT):
            this_needs_space = not (token.string in '+-#,;{}[]')

            if needs_space and this_needs_space:
                file.write(' ')
            file.write(token.string)

            needs_space = this_needs_space
            if token.string in ';#':
                accept_newline = True


def c_to_py_ast(c_src):
    """Convert C expression source str to a Python ast.Expression"""
    expr_node = src_to_c_ast(c_src)
    py_node = ast.fix_missing_locations(ast.Expression(to_py_ast(expr_node)))
    codeobj = compile(py_node, '<string>', 'eval')
    return eval(codeobj, {})


def c_to_py_src(c_src):
    """Convert C expression source str to a Python source str"""
    log.debug("Converting c-source '{}'".format(c_src))
    expr_node = src_to_c_ast(c_src)
    return ''.join(to_py_src(expr_node))


def src_to_c_ast(source):
    """Convert C expression source str to a c_ast expression node"""
    if ';' in source:
        raise ConvertError("C-to-Py supports only expressions, not statements")

    try:
        tree = cparser.parse('int main(void){' + source + ';}')
    except (plyparser.ParseError, AttributeError) as e:
        raise ConvertError(e)

    expr_node = tree.ext[0].body.block_items[0]
    return expr_node


def evaluate_c_src(src):
    val = c_to_py_ast(src)

    if isinstance(val, bool):
        result = Token(Token.NUMBER, str(int(val)))
    elif isinstance(val, (int, float)):
        result = Token(Token.NUMBER, str(val))
    elif isinstance(val, float):
        result = Token(Token.STRING_CONST, '"{}"'.format(val))
    else:
        raise Exception("Unknown result {}".format(val))

    return val, result


def to_py_ast(node):
    """Convert a c_ast expression into a Python ast object"""
    if isinstance(node, c_ast.UnaryOp):
        py_expr = to_py_ast(node.expr)
        py_node = ast.UnaryOp(UNARY_OPS[node.op](), py_expr)

    elif isinstance(node, c_ast.BinaryOp):
        py_left = to_py_ast(node.left)
        py_right = to_py_ast(node.right)
        if node.op in BINARY_OPS:
            py_node = ast.BinOp(py_left, BINARY_OPS[node.op](), py_right)
        elif node.op in CMP_OPS:
            py_node = ast.Compare(py_left, CMP_OPS[node.op](), py_right)
        elif node.op in BOOL_OPS:
            py_node = ast.BoolOp(py_left, py_right, BOOL_OPS[node.op]())
        else:
            raise ConvertError("Unsupported binary operator '{}'".format(node.op))

    elif isinstance(node, c_ast.Constant):
        if node.type == 'int':
            py_node = ast.Num(int(node.value.rstrip('UuLl'), base=0))
        elif node.type == 'float':
            # Not including the hex stuff from C++17
            py_node = ast.Num(float(node.value.rstrip('FfLl')))
        elif node.type == 'string':
            py_node = ast.Str(node.value.strip('"'))
        else:
            raise ConvertError("Unsupported constant type '{}'".format(node.type))

    elif isinstance(node, c_ast.TernaryOp):
        py_node = ast.IfExp(to_py_ast(node.cond), to_py_ast(node.iftrue), to_py_ast(node.iffalse))

    else:
        raise ConvertError("Unsupported c_ast type {}".format(type(node)))

    return py_node


# TODO: Convert this to using a generator pattern like CGenerator?
def to_py_src(node):
    """Convert a c_ast expression into a Python source code string list"""
    if isinstance(node, c_ast.UnaryOp):
        py_expr = to_py_src(node.expr)

        if node.op == 'sizeof':
            py_src = ['ffi.sizeof('] + py_expr + [')']
        else:
            py_src = ['(', UNARY_OP_STR[node.op]] + py_expr + [')']

    elif isinstance(node, c_ast.BinaryOp):
        py_left = to_py_src(node.left)
        py_right = to_py_src(node.right)

        # TODO: account for the Python/C99 difference of / and %
        if node.op in ALL_BINOP_STRS:
            py_src = ['('] + py_left + [ALL_BINOP_STRS[node.op]] + py_right + [')']
        else:
            raise ConvertError("Unsupported binary operator '{}'".format(node.op))

    elif isinstance(node, c_ast.Constant):
        if node.type == 'int':
            int_str = node.value.lower().rstrip('ul')
            if int_str.startswith('0x'):
                base = 16
            elif int_str.startswith('0b'):
                base = 2
            elif int_str.startswith('0'):
                base = 8
            else:
                base = 10
            py_src = [str(int(int_str, base))]
        elif node.type == 'float':
            py_src = [node.value.rstrip('FfLl')]
        elif node.type == 'string':
            py_src = [node.value]
        else:
            raise ConvertError("Unsupported constant type '{}'".format(node.type))

    elif isinstance(node, c_ast.ID):
        py_src = [node.name]

    elif isinstance(node, c_ast.TernaryOp):
        py_src = (['('] + to_py_src(node.iftrue) + [' if '] + to_py_src(node.cond) + [' else '] +
                  to_py_src(node.iffalse) + [')'])

    elif isinstance(node, c_ast.FuncCall):
        exprs = node.args.exprs if node.args else []
        args = ', '.join(''.join(to_py_src(e)) for e in exprs)
        py_src = [node.name.name, '(', args, ')']

    elif isinstance(node, c_ast.Cast):
        if not isinstance(node.to_type.type, c_ast.TypeDecl):
            raise ConvertError("Unsupported cast type {}".format(node.to_type.type))
        type_str = ' '.join(node.to_type.type.type.names)
        py_type = 'float' if ('float' in type_str or 'double' in type_str) else 'int'
        cast_str = 'ffi.cast("{}", '.format(type_str)
        py_src = [py_type, '(', cast_str, '('] + to_py_src(node.expr) + [')))']

    else:
        raise ConvertError("Unsupported c_ast type {}".format(type(node)))

    return py_src


def process_file(in_fname, out_fname, minify):
    with open(in_fname, 'rU') as f:
        tokens = lexer.lex(f.read())

    parser = Parser(tokens, REPLACEMENT_MAP)
    parser.parse()

    with open(out_fname, 'w') as f:
        if minify:
            write_tokens(f, parser)
        else:
            write_tokens_simple(f, parser)

    with open('macros.py', 'w') as f:
        #f.writelines("{} = {}\n".format(name, val) for name, val in parser.macro_vals.items())
        f.write("from builtins import int\n")
        for macro in parser.macros:
            if not macro.dependencies_satisfied:
                f.write("# ")
            f.write("{} = {}\n".format(macro.name, macro.py_src))


def to_str_seq(arg):
    return (arg,) if isinstance(arg, basestring) else arg


def process_headers(header_paths, predef_path=None, update_cb=None, ignored_headers=(),
                    ignore_system_headers=False, debug_file=None, preamble=None, token_hooks=(),
                    ast_hooks=(), hook_groups=(), return_ast=False, load_dump_file=False,
                    save_dump_file=False):
    """Preprocess header(s) and split into a cleaned header and macros

    Parameters
    ----------
    header_paths : str or sequence of strs
        Paths of the headers
    ignored_headers : sequence of strs
        Names of headers to ignore; `#include`\s containing these will be skipped.
    ignore_system_headers : bool
        If True, skip inclusion of headers specified with angle brackets, e.g. `#include
        <stdarg.h>` Header files specified with double quotes are processed as ususal. Default is
        False.
    debug_file : str
        File to write a partially-processed header to just before it is parsed by `pycparser`.
        Useful for debugging the preprocessor when `pycparser`'s parser chokes on its output.
    preamble : str
        C source to insert before the headers specified by `header_paths`. Useful for including
        typedefs that would otherwise be hard to reach due to an end user missing headers.
    token_hooks : sequence of functions
        Hook functions to be run on the already preprocessed token stream. Each function should
        accept and return a sequence of `Token`\s. These are applied after any builtin token hooks.
    ast_hooks : sequence of functions
        Hook functions to be run on chunks of the header's C AST. After preprocessing and running
        the token hooks, the tokens are grouped and joined to form a sequence of chunks called
        "external declarations" (declarations, typedefs, and function definitions). Each chunk is
        parsed by `pycparser`, then passed through the list of AST hook functions to transform it.
        These are applied after any builtin AST hooks.

        AST hook functions take the parsed `FileAST` and the persistent `CParser` instance as
        arguments, and return a transformed `FileAST`. It is useful to have a reference to the
        parser to add phony typedefs if necessary.
    hook_groups : str or sequence of strs
        Predefined hook groups to use. Each hook group enables certain builtin hooks that are
        commonly used together. The only hook group available for now is 'C++'.

        'C++' : (declspec_hook, extern_c_hook, enum_type_hook, CPPTypedefAdder)
            Hooks for converting C++-only headers into C syntax understandable by `cffi`.
    load_dump_file : bool
        Save the list of tokens resulting from preprocessing to 'token_dump.pkl'. See save_dump_file
        for more info.
    save_dump_file : bool
        Ignore `header_paths` and load the already-preprocessed tokens from 'token_dump.pkl'. This
        can significantly speed up your turnaround time when debugging really large header sets
        when writing and debugging hooks.

    Returns
    -------
    header_src : str
        Cleaned header C-code.
    macro_rc : str
        Extracted macros expressed as Python source code.
    """
    try:
        iter(token_hooks)
    except:
        token_hooks = (token_hooks, )
    hook_groups = to_str_seq(hook_groups)

    if load_dump_file:
        with open('token_dump.pkl', 'rb') as f:
            tokens = pkl.load(f)
        macros = []
        macro_expand = None
    else:
        header_paths = to_str_seq(header_paths)
        source = '\n'.join('#include "{}"'.format(path) for path in header_paths)

        if preamble:
            source = preamble + '\n' + source

        OBJ_MACROS, FUNC_MACROS = get_predef_macros()
        parser = Parser(source, '<root>', REPLACEMENT_MAP, OBJ_MACROS,
                        FUNC_MACROS, INCLUDE_DIRS, ignored_headers=ignored_headers,
                        ignore_system_headers=ignore_system_headers)
        parser.parse(update_cb=update_cb)
        tokens = parser.out
        macros = parser.macros
        macro_expand = parser.macro_expand
        log.info("Successfully parsed input headers")

        if save_dump_file:
            with open('token_dump.pkl', 'wb') as f:
                pkl.dump(parser.out, f, protocol=-1)

    token_hooks = tuple(token_hooks)
    ast_hooks = tuple(ast_hooks)
    for group in hook_groups:
        token_hooks += HOOK_GROUPS[group][0]
        ast_hooks += HOOK_GROUPS[group][1]

    gen = Generator(tokens, macros, macro_expand,
                    token_hooks=token_hooks,
                    ast_hooks=ast_hooks,
                    debug_file=debug_file)
    header_src, macro_src, tree = gen.generate()

    if return_ast:
        return header_src, macro_src, tree
    else:
        return header_src, macro_src


def generate_bindings(header_info, outfile, prefix=(), add_ret_ignore=False, niceobj_prefix={},
                      fill_handle=True, **kwds):
    """Generate a skeleton library wrapper.

    Grabs all the function declarations from the given header(s), generating a
    partially-implemented NiceLib wrapper that can be uncommented and filled in as you go. Supports
    NiceObjects and stripping of prefixes.

    Parameters
    ----------
    header_info, **kwds :
        These get passed directly to `process_headers()`
    outfile : str or file-like object
        File (or filename) where output is written.
    prefix : str or tuple of strs, optional
        Prefix(es) to strip from toplevel functions.
    add_ret_ignore : bool, optional
        Automatically add the 'ignore' return value wrapper for void C functions. False by default.
    niceobj_prefix : dict, optional
        Mapping from NiceObject name to its function prefix. If a function has this prefix, it will
        be considered a 'method' of the given NiceObject. These prefixes are checked before the
        top-level prefixes.
    fill_handle : bool, optional
        If True, automatically set the first argument of every NiceObject function to ``'in'``.
        True by default.
    """
    if isinstance(outfile, basestring):
        with open(outfile, 'w') as f:
            return generate_bindings(header_info, f, prefix, add_ret_ignore, niceobj_prefix,
                                     fill_handle, **kwds)

    print("Searching for headers...")
    header_paths, predef_path = handle_header_path(header_info)
    print("Found {}".format(header_paths))

    _, _, tree = process_headers(header_paths, return_ast=True, **kwds)
    toplevel_sigs = []
    niceobj_sigs = defaultdict(list)
    prefixes = (prefix, '') if isinstance(prefix, basestring) else prefix + ('',)

    for ext in tree.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.FuncDecl):
            funcdecl = ext.type
            func_name = funcdecl.type.declname
            is_niceobj = True
            for niceobj_name, prefix in niceobj_prefix.items():
                if func_name.startswith(prefix):
                    break
            else:
                is_niceobj = False
                for prefix in prefixes:
                    if func_name.startswith(prefix):
                        break
            func_name = func_name[len(prefix):]

            if funcdecl.args and funcdecl.args.params[0].name is not None:
                arg_names = [arg.name for arg in funcdecl.args.params]
                if is_niceobj and fill_handle:
                    arg_names[0] = "'in'"  # Auto-fill handle input

                sig = ', '.join(arg_names)
            else:
                sig = ''

            ret_type = ' '.join(funcdecl.type.type.names)
            if ret_type == 'void' and add_ret_ignore:
                if sig:
                    sig += ", {'ret': 'ignore'}"
                else:
                    sig = "{'ret': 'ignore'},"

            fullsig = '# {} = ({})\n'.format(func_name, sig)
            if is_niceobj:
                niceobj_sigs[niceobj_name].append(fullsig)
            else:
                toplevel_sigs.append(fullsig)

    outfile.write("from nicelib import NiceLib, NiceObjectDef\n\n\n")
    outfile.write("class MyNiceLib(NiceLib):\n")
    outfile.write("    # _info = load_lib('mylibname')\n")
    outfile.write("    _prefix = {}\n\n".format(repr(prefix)))

    indent = '    '
    for sig in toplevel_sigs:
        outfile.write(indent)
        outfile.write(sig)

    for niceobj_name, sigs in niceobj_sigs.items():
        if niceobj_name:
            outfile.write("\n")
            outfile.write(indent)
            outfile.write("{} = NiceObjectDef(prefix='{}', "
                          "args=dict(\n".format(niceobj_name, niceobj_prefix[niceobj_name]))
            for sig in sigs:
                outfile.write(indent*2)
                outfile.write(sig)
            outfile.write("\n" + indent + "))\n")


#
# Hooks
#

def modify_pattern(tokens, pattern):
    """Helper function for easily matching and modifying patterns in a token stream

    Parameters
    ----------
    tokens : sequence of Tokens
        Input token stream to process
    pattern : sequence of tuples
        Pattern to match, as a sequence of (keep, target) pairs. Targets are compared against
        tokens; when the first target is matched, we then try matching the rest in order. If the
        whole pattern is matched, each target's corresponding ``keep`` indicates whether the token
        should be kept in the sequence, or discarded. ``keep`` is a string, where 'k' means 'keep',
        'd' means discard and 'a' means add.

        A ``target`` can be either a string or a `TokenType`.

        There is also some functionality for dealing with blocks enclosed in curly braces {}. For
        more advanced functionality, check out `ParseHelper`.

        Passing a sequence of the type ``((keep_start, '{'), ('keep_end', '~~}~~'))`` will keep the
        opening ``{`` according to ``keep_start``. ``keep_end`` is a two letter string, where the
        first letter indicates whether the contents of the block enclosed in braces should be kept,
        and the second indicates if the closing ``}`` should be kept.
    """
    # Check that only the correct keywords are passed
    allowed_keywords = ('a', 'k', 'd', 'kd', 'kk', 'dk', 'dd')
    try:
        assert all(pattern_element[0] in allowed_keywords for pattern_element in pattern)
    except:
        raise TypeError("Incorrect keyword for modify_pattern."
                        "Allowed keywords are {}".format(allowed_keywords))

    # Convert any strings that are paired with 'a' keywords to tokens
    for i in range(len(pattern)):
        keep, target = pattern[i]
        if keep == 'a':
            pattern[i] = (keep, lexer.read_token(target))
    it = iter(tokens)
    p_it = iter(pattern)
    keep, target = next(p_it)
    if keep != 'a':
        t = next(it)
    match_buf = []
    depth = 0
    pattern_completed = False

    def matches(token, target):
        if isinstance(target, TokenType):
            return token.type is target
        elif isinstance(target, basestring):
            return token.string == target
        return False

    while True:
        if keep == 'a':
                # This target should be inserted
                match_buf.append((keep, target))
                try:
                    keep, target = next(p_it)
                except StopIteration:
                    pattern_completed = True
        elif isinstance(target, basestring) and target.startswith('~~') and target.endswith('~~'):
            found_end = False
            right = target[2]
            left = {'}': '{', ')': '(', ']': '['}[right]

            if t.string == left:
                depth += 1
            elif t.string == right:
                if depth == 0:
                    found_end = True
                else:
                    depth -= 1

            if found_end:
                match_buf.append((keep[1] if len(keep) > 1 else keep, t))
                try:
                    keep, target = next(p_it)
                except StopIteration:
                    pattern_completed = True
            else:
                match_buf.append((keep[0], t))

        else:
            # Ignore non-tokens
            if t.type in NON_TOKENS:
                if match_buf:
                    match_buf.append((keep, t))
                else:
                    yield t

            elif matches(t, target):
                # Found target
                match_buf.append((keep, t))
                try:
                    keep, target = next(p_it)
                except StopIteration:
                    pattern_completed = True

            else:
                # Reset pattern matching
                if match_buf:
                    p_it = iter(pattern)
                    keep, target = next(p_it)
                    for keep_tok, buf_tok in match_buf:
                        yield buf_tok
                    match_buf = []
                yield t

        if pattern_completed and match_buf:
            p_it = iter(pattern)
            keep, target = next(p_it)
            for keep_tok, buf_tok in match_buf:
                if keep_tok in ('k', 'a'):
                    yield buf_tok
            match_buf = []
            pattern_completed = False

        try:
            if keep != 'a':
                t = next(it)
        except StopIteration:
            # Output pending buffers
            for keep_tok, buf_tok in match_buf:
                if keep_tok == 'k':
                    yield buf_tok
            raise StopIteration


def remove_pattern(tokens, pattern):
    """Convenience function that works like `modify_pattern`, but you only specify targets"""
    pattern = [('d', target) for target in pattern]
    return modify_pattern(tokens, pattern)


def add_line_directive_hook(tokens):
    """Adds line directives to indicate where each token came from

    Enabled by default.
    """
    out_tokens = []
    chunk = []
    expected_line = -1
    cur_fpath = '<root>'
    chunk_start_line = -1
    high_mark, low_mark = 0, -1
    for t in tokens:
        if (t.fpath, t.line) != (cur_fpath, expected_line):
            if high_mark > low_mark >= 0:
                # For some reason the lexer's eating the trailing newline so we use two
                line_tokens = lexer.lex('\n#line {} "{}"\n\n'.format(chunk_start_line + low_mark,
                                                                     cur_fpath))
                out_tokens.extend(line_tokens)
                out_tokens.extend(chunk[low_mark:high_mark])
            cur_fpath = t.fpath
            expected_line = t.line
            chunk = []
            high_mark, low_mark = 0, -1
            chunk_start_line = t.line

        if t.type not in NON_TOKENS:
            high_mark = len(chunk) + 1
            if low_mark == -1:
                low_mark = len(chunk)
        elif t.type is Token.NEWLINE:
            expected_line += 1
        elif t.type is Token.BLOCK_COMMENT:
            continue  # Don't output
        elif t.type is Token.LINE_COMMENT:
            continue  # Don't output

        chunk.append(t)

    # Add trailing chunk
    if high_mark > low_mark >= 0:
        line_tokens = lexer.lex('\n#line {} "{}"\n\n'.format(chunk_start_line, cur_fpath))
        out_tokens.extend(line_tokens)
        out_tokens.extend(chunk[low_mark:high_mark])

    return out_tokens


def declspec_hook(tokens):
    """Removes all occurences of `__declspec(...)`"""
    return remove_pattern(tokens, ['__declspec', '(', '~~)~~'])


def cdecl_hook(tokens):
    """Removes `cdecl`, `_cdecl`, and `__cdecl`

    Enabled by default.
    """
    for token in tokens:
        if token not in ('cdecl', '_cdecl', '__cdecl'):
            yield token


def inline_hook(tokens):
    """Removes `_inline`, `__inline`, and `__forceinline`"""
    for token in tokens:
        if token not in ('_inline', '__inline', '__forceinline'):
            yield token


def extern_c_hook(tokens):
    """Removes `extern "C" { ... }` while keeping the block's contents"""
    return modify_pattern(tokens, [('d', 'extern'), ('d', '"C"'), ('d', '{'), ('kd', '~~}~~')])


def enum_type_hook(tokens):
    """Removes enum type, e.g. `enum myEnum : short {...};` becomes `enum myEnum {...};`"""
    return modify_pattern(tokens, [('k', 'enum'), ('k', Token.IDENTIFIER), ('d', ':'),
                                   ('d', Token.IDENTIFIER)])


class ParseHelper(object):
    """Helper class for processing token streams

    Allows you to easily read until specific tokens or the ends of blocks, etc.
    """
    def __init__(self, tokens):
        self.tokens = tokens
        self.tok_it = iter(tokens)
        self.depth = 0
        self.peek_deque = deque()
        self.peek_deque.append(next(self.tok_it))

    def pop(self):
        """Pop and return next token

        Raises StopIteration if we're already at the end of the token stream.
        """
        try:
            token = self.peek_deque.popleft()
        except IndexError:
            raise StopIteration

        try:
            if not self.peek_deque:
                self.peek_deque.append(next(self.tok_it))
        except StopIteration:
            pass

        if token in ('(', '{', '['):
            self.depth += 1
        elif token in (')', '}', ']'):
            self.depth -= 1

        return token

    def peek(self):
        """Peek at the next token

        Returns None at the end of the token stream.
        """
        return self.peek_deque[0] if self.peek_deque else None

    def peek_true_token(self):
        """Peek at next true token

        "True" tokens are non-whitespace and non-comment tokens.

        Returns None at the end of the token stream.
        """
        for token in self.peek_deque:
            if token not in NON_TOKENS:
                return token

        for token in self.tok_it:
            self.peek_deque.append(token)
            if token not in NON_TOKENS:
                return token

        return None

    def read_until(self, tokens, discard=False):
        """Read until the given token, but do not consume it

        Raises StopIteration if we're already at the end of the token stream.
        """
        if isinstance(tokens, basestring) or not isinstance(tokens, Sequence):
            tokens = (tokens,)
        buf = []

        while True:
            token = self.peek()
            if token is None:
                if buf:
                    return buf
                raise StopIteration

            if token in tokens:
                return True if discard else buf

            if not discard:
                buf.append(token)

            self.pop()

    def read_to(self, tokens, discard=False):
        """Read to the given token and consume it

        Raises StopIteration if we're already at the end of the token stream.
        """
        if isinstance(tokens, basestring) or not isinstance(tokens, Sequence):
            tokens = (tokens,)
        buf = []

        while True:
            try:
                token = self.pop()
            except StopIteration:
                if buf:
                    return buf
                raise StopIteration

            if not discard:
                buf.append(token)

            if token in tokens:
                return True if discard else buf

    def read_to_depth(self, depth, discard=False):
        """Read until the specified nesting depth or the end of the token stream

        If `discard` is False, returns a list of the tokens seen before either reaching the desired
        depth or end-of-stream.

        If `discard` is True, returns True on reaching the desired depth, and raises StopIteration
        on end-of-stream.

        Always raises StopIteration if we're already at the end of the token stream.

        Seeing a `(`, `{`, or `[` increases the depth, and seeing a `)`, `}`, or `]` decreases it.
        The current depth is available via the `depth` attribute.
        """
        buf = []

        while True:
            try:
                token = self.pop()
            except StopIteration:
                if buf:
                    return buf
                raise StopIteration

            if not discard:
                buf.append(token)

            if self.depth == depth:
                return True if discard else buf


def asm_hook(tokens):
    """Remove `_asm` and `__asm` and their blocks"""
    ph = ParseHelper(tokens)

    while True:
        for token in ph.read_until(('_asm', '__asm')):
            yield token
        ph.pop()  # Get rid of '__asm'

        if ph.peek_true_token() == '{':
            ph.read_to('{', discard=True)
            ph.read_to_depth(ph.depth-1, discard=True)
        else:
            ph.read_to('\n', discard=True)

        next_true_token = ph.peek_true_token()
        if next_true_token in (';', '_asm', '__asm'):
            ph.read_until(next_true_token, discard=True)
        else:
            yield Token(Token.PUNCTUATOR, ';')


def stdcall_hook(tokens):
    """Replace `__stdcall` and `WINAPI` with `volatile volatile const`

    Enabled by default.

    This technique is stolen from `cffi`.
    """
    ph = ParseHelper(tokens)

    while True:
        token = ph.pop()
        if token == '(':
            if ph.peek_true_token() in ('__stdcall', 'WINAPI'):
                ph.read_to(('__stdcall', 'WINAPI'))  # Discard
                for t in lexer.lex(' volatile volatile const ('):
                    yield t
            else:
                yield token
        elif token in ('__stdcall', 'WINAPI'):
            for t in lexer.lex(' volatile volatile const '):
                yield t
        else:
            yield token


def vc_pragma_hook(tokens):
    """Remove `__pragma(...)`"""
    ph = ParseHelper(tokens)

    while True:
        for token in ph.read_until('__pragma'):
            yield token

        # Throw away pragmas
        ph.read_to('(', discard=True)
        ph.read_to_depth(ph.depth-1, discard=True)


def struct_func_hook(tokens):
    """Removes function definitions from inside struct definitions.

    Once we're inside the struct's curly braces, we look member-by-member. We push each next token
    into a buffer, if we see an open brace then we assume this member is a funcdef. The funcdef is
    over after the matching close brace and an optional semicolon. Otherwise, if we see a semicolon
    outside of any nesting, that's the end of an ordinary member declaration.

    NOTE: Does not deal with nested structs that have methods (if that's even allowed).

    If we see a funcdef, throw away all its tokens. If we see a member declaration, pass the tokens
    on.
    """
    ph = ParseHelper(tokens)

    while True:
        for token in ph.read_to('struct'):
            yield token
        if token != 'struct':
            raise StopIteration

        # Yield until opening of struct def (or end of statement)
        start_depth = ph.depth
        maybe_a_def = True
        in_struct_def = False
        done = False
        while not done:
            token = ph.pop()
            yield token

            if ph.depth == start_depth and token == ';':
                done = True
            elif ph.depth == start_depth and token == '=':
                maybe_a_def = False
            elif maybe_a_def and token == '{':
                done = True
                in_struct_def = True

        if not in_struct_def:
            continue

        struct_def_done = False
        while not struct_def_done:
            # Process each member
            buf = []
            member_depth = ph.depth
            member_done = False
            sue_proximity = 99
            while not member_done:
                token = ph.pop()
                buf.append(token)

                if token not in NON_TOKENS:
                    sue_proximity += 1

                if token in ('struct', 'union', 'enum'):
                    sue_proximity = 0

                if sue_proximity > 2 and token == '{':
                    # In a funcdef, ignore these tokens
                    buf = []
                    ph.read_to_depth(ph.depth - 1, discard=True)

                    # Discard optional semicolon
                    if ph.peek() == ';':
                        ph.pop()
                    member_done = True

                elif ph.depth == member_depth and token == ';':
                    # End of ordinary member declaration
                    member_done = True

                elif ph.depth == member_depth - 1:
                    member_done = True
                    struct_def_done = True

            for token in buf:
                yield token


#
# AST Hooks
#

def add_typedef_hook(tree, parse_func):
    """Wraps enum/struct/union definitions in a typedef if they lack one

    Useful for C++ headers where the typedefs are implicit.
    """
    return CPPTypedefAdder().hook(tree, parse_func)


class CPPTypedefAdder(TreeModifier):
    """Wraps enum/struct/union definitions in a typedef if they lack one"""
    def hook(self, tree, parse_func):
        # Reset these every call
        self.in_typedef = False
        self.added_types = set()

        tree = self.visit(tree)

        if self.added_types:
            # Add fake typedefs so the parser doesn't choke
            parse_func('\n'.join('typedef int {};'.format(t) for t in self.added_types))
        return tree

    def visit_Typedef(self, node):
        self.in_typedef = True
        result = self.generic_visit(node)
        self.in_typedef = False
        return result

    def visit_EnumStructUnion(self, node):
        if self.in_typedef:
            return node
        else:
            self.added_types.add(node.name)
            typedecl_node = c_ast.TypeDecl(node.name, [], node)
            return c_ast.Typedef(node.name, [], ['typedef'], typedecl_node)

    def visit_Enum(self, node):
        return self.visit_EnumStructUnion(node)

    def visit_Struct(self, node):
        return self.visit_EnumStructUnion(node)

    def visit_Union(self, node):
        return self.visit_EnumStructUnion(node)


HOOK_GROUPS = {
    'C++': ((declspec_hook, extern_c_hook, enum_type_hook, struct_func_hook),
            (CPPTypedefAdder().hook,)),
}
