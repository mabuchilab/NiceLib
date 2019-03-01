# -*- coding: utf-8 -*-
# Copyright 2018 Nate Bogdanowicz

# Modeled after pycparserext
from pycparser.c_generator import CGenerator
from pycparser.c_ast import NodeVisitor
from pycparser import c_ast


class CPPGenerator(CGenerator):
    def generate(self, node):
        self.finder = MultiTypedefFinder()
        self.finder.visit(node)
        return self.visit(node)

    def visit_FileAST(self, node):
        # Mostly copied from CGenerator
        s = ''
        for ext in node.ext:
            if isinstance(ext, c_ast.FuncDef):
                s += self.visit(ext)
            elif isinstance(ext, c_ast.Pragma):
                s += self.visit(ext) + '\n'
            elif node not in self.finder.extra_typedefs:
                s += self.visit(ext) + ';\n'


class MultiTypedefFinder(NodeVisitor):
    def __init__(self):
        self.outer_typedef = None
        self.struct_typedefs = {}  # Maps struct:[typedefs]
        self.first_typedefs = set()
        self.extra_typedefs = set()

    def visit_Typedef(self, node):
        self.outer_typedef = node
        self.visit(node.type)
        self.outer_typedef = None

    def visit_Struct(self, node):
        # FIXME: What do we do about nested struct definitions?
        if not self.outer_typedef:
            return
        if node not in self.struct_typedefs:
            self.struct_typedefs[node] = [self.outer_typedef]
            self.first_typedefs.add(self.outer_typedef)
        else:
            self.struct_typedefs[node].append(self.outer_typedef)
            self.extra_typedefs.add(self.outer_typedef)
