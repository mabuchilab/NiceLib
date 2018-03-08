# -*- coding: utf-8 -*-
# Copyright 2018 Nate Bogdanowicz

# Modeled after pycparserext
from __future__ import division

from pycparser.c_parser import CParser
from pycparser import c_ast

from .cpp_lexer import CPPLexer


class CPPParser(CParser):
    def __init__(self, **kwds):
        kwds['lexer'] = CPPLexer
        kwds['lextab'] = 'nicelib.parser.lextab'
        kwds['yacctab'] = 'nicelib.parser.yacctab'
        CParser.__init__(self, **kwds)

    # Parse pass-by-ref args as pointers
    def p_pointer(self, p):
        """ pointer : TIMES type_qualifier_list_opt
                    | TIMES type_qualifier_list_opt pointer
                    | AND type_qualifier_list_opt
                    | AND type_qualifier_list_opt pointer
        """
        return CParser.p_pointer(self, p)

    # Parse typed enums, but ignore the types
    def p_enum_specifier_4(self, p):
        """ enum_specifier : ENUM ID COLON declaration_specifiers brace_open enumerator_list brace_close
                           | ENUM TYPEID COLON declaration_specifiers brace_open enumerator_list brace_close
        """
        p[0] = c_ast.Enum(p[2], p[6], self._token_coord(p, 1))
