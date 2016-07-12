# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
from __future__ import unicode_literals, division, print_function
from future import standard_library
standard_library.install_aliases()
from builtins import str, range
from past.builtins import basestring

import re
import os.path
import warnings
import logging as log
from enum import Enum
from collections import OrderedDict, namedtuple, defaultdict
import ast
from io import StringIO
from pycparser import c_parser, c_generator, c_ast, plyparser
import cffi
import cffi.commontypes
from .platform import PREDEF_MACRO_STR, REPLACEMENT_MAP, INCLUDE_DIRS

'__cplusplus', '__linux__', '__APPLE__', '__CVI__', '__TPC__'

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
    def __init__(self, type, string, line=0, col=0, fpath='<string>'):
        self.type = type
        self.string = string
        self.line = line
        self.col = col
        self.fpath = fpath

    def matches(self, other_type, other_string):
        return self.type is other_type and self.string == other_string

    def __str__(self):
        string = '' if self.string == '\n' else self.string
        return '{}[{}:{}:{}]({})'.format(self.type.name, self.fpath, self.line, self.col, string)

    def __repr__(self):
        return str(self)

for ttype in TokenType:
    setattr(Token, ttype.name, ttype)

NON_TOKENS = (Token.WHITESPACE, Token.NEWLINE, Token.LINE_COMMENT, Token.BLOCK_COMMENT)


class Lexer(object):
    def __init__(self):
        self.regexes = OrderedDict()
        self.ignored = []

    def add(self, name, regex_str, ignore=False):
        self.regexes[name] = re.compile(regex_str)
        if ignore:
            self.ignored.append(name)

    def lex(self, text, fpath='<string>'):
        self.line = 1
        self.col = 1
        self.fpath = fpath
        self.esc_newlines = defaultdict(int)

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
        tokens = []
        pos = 0
        while pos < len(text):
            token = self.read_token(text, pos)
            if token is None:
                raise LexError("No acceptable token found!")
            if token.type not in self.ignored:
                tokens.append(token)
            pos = pos + len(token.string)

            for i in range(token.string.count('\n')):
                self.line += 1 + self.esc_newlines.get(self.line, 0)
                self.col = 1
            self.col += len(token.string.rsplit('\n', 1)[-1])

        return tokens

    def read_token(self, text, pos=0):
        """Read the next token from text, starting at pos"""
        best_token = None
        best_size = 0
        for token_type, regex in self.regexes.items():
            match = regex.match(text, pos)
            if match:
                size = match.end() - match.start()
                if size > best_size:
                    best_token = Token(token_type, match.group(0), self.line, self.col, self.fpath)
                    best_size = size
        return best_token


def build_c_lexer():
    lexer = Lexer()
    lexer.add(Token.DEFINED, r"defined")
    lexer.add(Token.IDENTIFIER, r"[a-zA-Z_][a-zA-Z0-9_]*")
    lexer.add(Token.NUMBER, r'\.?[0-9]([0-9a-zA-Z_.]|([eEpP][+-]))*')
    lexer.add(Token.STRING_CONST, r'"([^"\\\n]|\\.)*"')
    lexer.add(Token.CHAR_CONST, r"'([^'\\\n]|\\.)*'")
    lexer.add(Token.HEADER_NAME, r"<[^>\n]*>")
    lexer.add(Token.PUNCTUATOR,
              r"[<>=*/*%&^|+-]=|<<==|>>==|\.\.\.|->|\+\+|--|<<|>>|&&|[|]{2}|##|"
              r"[{}\[\]()<>.&*+-~!/%^|=;:,?#]")
    lexer.add(Token.NEWLINE, r"\n", ignore=False)
    lexer.add(Token.WHITESPACE, r"[ \t]+", ignore=False)
    lexer.add(Token.LINE_COMMENT, r"//.*($|(?=\n))", ignore=False)
    lexer.add(Token.BLOCK_COMMENT, r"/\*(.|\n)*?\*/", ignore=False)
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
                 include_dirs=[], ignore_headers=()):
        self.base_dir, self.fname = os.path.split(fpath)
        self.tokens = lexer.lex(source, fpath)
        self.last_line = self.tokens[-1].line
        self.replacement_map = replacement_map
        self.out = []
        self.cond_stack = []
        self.cond_done_stack = []
        self.include_dirs = include_dirs
        self.ignored_headers = tuple(os.path.normcase(p) for p in ignore_headers)

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
            warnings.warn("#undef of nonexistent macro '{}'".format(name))

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
                update_cb(self.out[-1].line, self.last_line)

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

            expanded = self.macro_expand_2([token] + self.tokens[:last_newline_idx])
            self.tokens = self.tokens[last_newline_idx:]

            # Add to output
            if not self.skipping:
                for token in expanded:
                    self.out.append(token)
                    self.perform_replacement()

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

    def macro_expand_2(self, tokens, blacklist=[], func_blacklist=[]):
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
                        raise ParseError(name_token, "Func-like macro needs {} arguments, got "
                                         "{}".format(len(macro.args), len(arg_lists)))

                    # Expand args
                    exp_arg_lists = [self.macro_expand_2(a, blacklist, func_blacklist +
                                                         [name]) for a in arg_lists]

                    # Substitute args into body, then expand it
                    body = self.macro_expand_funclike_body(macro, exp_arg_lists)
                    expanded.extend(body)

                    if tokens:
                        token = tokens.pop(0)
                    else:
                        done = True
                else:
                    if self.obj_macro_defined(token.string) and token.string not in blacklist:
                        # Object-like macro expand
                        body = self.get_obj_macro(token.string).body
                        expanded.extend(self.macro_expand_2(body, blacklist + [token.string],
                                                            func_blacklist))
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

    def macro_expand_funclike_body(self, macro, exp_arg_lists, blacklist=[], func_blacklist=[]):
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
                substituted.append(token)

        # Do concatting pass
        for token in substituted:
            if concatting:
                if token.type not in NON_TOKENS:
                    concat_str = last_real_token.string + token.string
                    log.debug("Macro concat produced '{}'".format(concat_str))
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
        return self.macro_expand_2(body, blacklist, func_blacklist + [macro.name])

    def macro_expand_tokens(self, tokens, blacklist=[]):
        expanded = []
        for token in tokens:
            if (token.type is Token.IDENTIFIER and self.obj_macro_defined(token.string) and
                    token.string not in blacklist):
                vals = self.get_obj_macro(token.string).body
                vals = self.macro_expand_tokens(vals, blacklist + [token.string])
                expanded.extend(vals)
            else:
                expanded.append(token)
        return expanded

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

        exp = self.macro_expand_2(expanded)
        tokens = []
        for token in exp:
            if token.type is Token.IDENTIFIER:
                warnings.warn(PreprocessorWarning(token, "Unidentified identifier {} in expression"
                                                  ", treating as 0...".format(token.string)))
                tokens.append(Token(Token.NUMBER, '0'))
            else:
                tokens.append(token)

        py_src = c_to_py_src(' '.join(token.string for token in tokens))
        log.info("py_src = '{}'".format(py_src))
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
        self.assert_line_empty()
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
                log.info("Saving func-macro {} = {}".format(macro, body))
        else:
            # Object-like macro
            dont_ignore = (Token.WHITESPACE, Token.BLOCK_COMMENT, Token.LINE_COMMENT)
            tokens = self.pop_until_newline(silent=True, dont_ignore=dont_ignore)

            if not self.skipping:
                preamble, body, postamble = self._split_body(tokens)
                macro = Macro(name_token, body)
                self.add_obj_macro(macro)
                log.info("Saving obj-macro {} = {}".format(macro, body))

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
        self.pop_until_newline()  # Ignore pragmas
        return False

    def parse_error(self):
        tokens = self.pop_until_newline()
        if not self.skipping:
            log.info("obj_macros = {}".format(self.obj_macros))
            log.info("func_macros = {}".format(self.func_macros))
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

        if os.path.normcase(hpath) in self.ignored_headers:
            log.info("Explicitly ignored header '{}'".format(hpath))
            return False

        if token.type is Token.HEADER_NAME:
            log.info("System header {}".format(hpath))
            for include_dir in self.include_dirs:
                try_path = os.path.join(include_dir, hpath)
                if os.path.exists(try_path):
                    hpath = try_path
                    break
        else:
            # TODO: Don't use base_dir if hpath is absolute
            base_dir = os.path.split(token.fpath)[0]
            hpath = os.path.join(base_dir, hpath)
            log.info("Local header {}".format(hpath))

        if os.path.exists(hpath):
            log.info("Including header {}".format(hpath))
            with open(hpath, 'rU') as f:
                tokens = lexer.lex(f.read(), hpath)
                tokens.append(Token(Token.NEWLINE, '\n'))

            # Prepend this header's tokens
            self.tokens = tokens + self.tokens
        else:
            raise PreprocessorError(token, 'Header "{}" not found'.format(hpath))

        return False


class FFICleaner(c_ast.NodeVisitor):
    def __init__(self, ffi):
        self.ffi = ffi
        self.generator = c_generator.CGenerator()
        self.defined_tags = set()

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

    def visit_Typedef(self, node):
        # Visit typedecl hierarchy first
        self.visit(node.type)

        # Now add type to FFI
        src = self.generator.visit(node) + ';'
        print(src)
        self.ffi.cdef(src)
        return node

    def visit_Enum(self, node):
        if node.values:  # Is a definition
            if node.name in self.defined_tags:
                node = c_ast.Enum(node.name, ())
            else:
                self.defined_tags.add(node.name)
                self.generic_visit(node)
        return node

    def visit_StructOrUnion(self, node, node_class):
        if node.decls:  # Is a definition
            if node.name in self.defined_tags:
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
        return node

    @staticmethod
    def _val_from_const(const):
        assert isinstance(const, c_ast.Constant)
        if const.type == 'int':
            int_str = const.value.rstrip('UuLl')
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
            print("SIZEOF({})".format(type_str))
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
    def __init__(self, parser, token_list_hooks=(), str_list_hooks=(), debug_file=None):
        self.tokens = parser.out
        self.macros = parser.macros
        self.expander = parser.macro_expand_2

        self.token_list_hooks = token_list_hooks
        self.str_list_hooks = str_list_hooks
        self.debug_file = debug_file

    def generate(self):

        # HOOK: list of tokens
        tokens = self.tokens
        for hook in self.token_list_hooks:
            tokens = hook(tokens)

        strings = []
        chunk = []
        expected_line = -1
        cur_fpath = '<root>'
        chunk_not_empty = False
        chunk_start_line = -1
        for t in tokens:
            if (t.fpath, t.line) != (cur_fpath, expected_line):
                if chunk_not_empty:
                    strings.append('#line {} "{}"\n'.format(chunk_start_line, cur_fpath))
                    strings.extend(chunk)
                cur_fpath = t.fpath
                expected_line = t.line
                chunk = []
                chunk_not_empty = False
                chunk_start_line = t.line

            if t.type not in NON_TOKENS:
                chunk_not_empty = True
            elif t.type is Token.NEWLINE:
                expected_line += 1
            elif t.type is Token.BLOCK_COMMENT:
                expected_line += t.string.count('\n')
                continue  # Don't output
            elif t.type is Token.LINE_COMMENT:
                continue  # Don't output

            chunk.append(t.string)

        # HOOK: list of strings
        for hook in self.str_list_hooks:
            strings = hook(strings)

        out = StringIO()

        # pycparser doesn't know about these types by default, but cffi does. We just need to make
        # sure that pycparser knows these are types, the particular type is unimportant
        for type_name in cffi.commontypes.COMMON_TYPES:
            out.write("typedef int {};\n".format(type_name))
        out.write(''.join(strings))

        # Do stdcall/WINAPI replacement hack like cffi does (see cffi.cparser for more info)
        r_stdcall1 = re.compile(r"\b(__stdcall|WINAPI)\b")
        r_stdcall2 = re.compile(r"[(]\s*(__stdcall|WINAPI)\b")
        r_cdecl = re.compile(r"\b__cdecl\b")
        csource = out.getvalue()
        csource = r_stdcall2.sub(' volatile volatile const(', csource)
        csource = r_stdcall1.sub(' volatile volatile const ', csource)
        csource = r_cdecl.sub(' ', csource)

        # Log intermediate c-source
        if self.debug_file:
            with open(self.debug_file, 'w') as f:
                f.write(csource)

        self.parser = c_parser.CParser()
        tree = self.parse(csource)
        # Remove phony typedefs
        tree.ext = tree.ext[len(cffi.commontypes.COMMON_TYPES):]

        log.info("pycparser successfully re-parsed cleaned header")

        # Remove function defs and replace 'volatile volatile const'
        ffi = cffi.FFI()
        cleaner = FFICleaner(ffi)
        tree = cleaner.visit(tree)

        # Generate cleaned C source
        generator = c_generator.CGenerator()
        header_src = generator.visit(tree)

        with open('log.txt', 'w') as f:
            f.write(header_src)

        # Convert macros
        macro_src = StringIO()
        macro_src.write("# Generated macro definitions\n")
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
                    macro_src.write("defs.{} = lambda {}: {}\n".format(macro.name, arg_list,
                                                                       py_src))
                else:
                    macro_src.write("defs.{} = {}\n".format(macro.name, py_src))

        return header_src, macro_src.getvalue()

    def gen_py_src(self, macro):
        prefix = '__FMACRO_' if isinstance(macro, FuncMacro) else '__OMACRO_'
        log.debug("Generating body of macro {} "
                  "[{}:{}:{}]".format(macro.name, macro.fpath, macro.line, macro.col))

        py_src = None
        if macro.body:
            expanded = self.expander(macro.body)
            for token in expanded:
                if token.type is Token.IDENTIFIER:
                    return None
            c_src = ''.join(token.string for token in expanded)
            func_src = "\nint " + prefix + macro.name + "(void){" + c_src + ";}"

            try:
                tree = self.parse(func_src)
                expr_node = tree.ext[0].body.block_items[0]
                try:
                    py_src = ''.join(to_py_src(expr_node))
                except ConvertError as e:
                    warnings.warn(e)

            except (plyparser.ParseError, AttributeError):
                warnings.warn("Un-pythonable macro {}".format(macro.name))

        return py_src

    def parse(self, text):
        """Reimplement CParser.parse to retain scope"""
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
    log.info("Converting c-source '{}'".format(c_src))
    expr_node = src_to_c_ast(c_src)
    return ''.join(to_py_src(expr_node))


def src_to_c_ast(source):
    """Convert C expression source str to a c_ast expression node"""
    if ';' in source:
        raise ConvertError("C-to-Py supports only expressions, not statements")
    parser = c_parser.CParser()

    try:
        tree = parser.parse('int main(void){' + source + ';}')
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
            int_str = node.value.rstrip('UuLl')
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
        args = ', '.join(''.join(to_py_src(e)) for e in node.args.exprs)
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


def process_headers(header_paths, predef_path=None, update_cb=None, ignore_headers=(),
                    debug_file=None):
    header_paths = (header_paths,) if isinstance(header_paths, basestring) else header_paths
    source = '\n'.join('#include "{}"'.format(path) for path in header_paths)

    OBJ_MACROS, FUNC_MACROS = get_predef_macros()
    parser = Parser(source, '<root>', REPLACEMENT_MAP, OBJ_MACROS,
                    FUNC_MACROS, INCLUDE_DIRS, ignore_headers=ignore_headers)
    parser.parse(update_cb=update_cb)
    log.info("Successfully parsed input headers")

    def extern_c_hook(strings):
        out = []
        looking_for_brace = False
        depth = 0
        i = 0
        while i < len(strings):
            s = strings[i]
            if not looking_for_brace:
                if s == 'extern' and i + 1 < len(strings) and strings[i+1] == '"C"':
                    depth = 0
                    looking_for_brace = True
                    i += 1
                else:
                    out.append(s)
            else:
                skip = False
                if s == '{':
                    skip = (depth == 0)
                    depth += 1
                elif s == '}':
                    depth -= 1
                    skip = (depth == 0)
                    looking_for_brace = not skip
                    i += 1  # Skip semicolon

                if not skip:
                    out.append(s)
            i += 1
        return out

    gen = Generator(parser, str_list_hooks=(extern_c_hook,), debug_file=debug_file)
    header_src, macro_src = gen.generate()
    return header_src, macro_src


if __name__ == '__main__':
    process_file('./NIDAQmx.h', './NIDAQmx_clean.h', minify=True)
    #process_file('uc480.h', 'uc480_clean.h', minify=True)


# NOTES
# =====

# - pycparser needs typedefs to be able to parse properly, e.g. "(HCAM)0" won't parse unless HCAM
# has been typedef'd (or already macro expanded to a valid type)
