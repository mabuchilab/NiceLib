# -*- coding: utf-8 -*-
# Copyright 2018 Nate Bogdanowicz

import sys
sys.path[0:0] = ['...']
from nicelib.parser import cpp_parser


# Generate the tables
cpp_parser.CPPParser(
    lex_optimize=True,
    yacc_debug=False,
    yacc_optimize=True,
)
