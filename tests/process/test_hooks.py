from util import local_fpath
from nicelib.process import (lexer, add_line_directive_hook, declspec_hook, extern_c_hook,
                             enum_type_hook, struct_func_hook)


def use_hook(hook, src):
    """Takes and return a header source string"""
    tokens = lexer.lex(src)
    tokens = hook(tokens)
    return ''.join(t.string for t in tokens)


# add_line_directive
# declspec

#
# extern_c
#
EXTERN_C_SRC = """
extern "C" {
    int abc = 123;
}
"""

def test_extern_c_hook():
    src = use_hook(extern_c_hook, EXTERN_C_SRC)
    assert 'extern' not in src
    assert '{' not in src
    assert '}' not in src
    assert 'abc' in src
    assert '123' in src


#
# enum_type
#
ENUM_TYPE_SRC = """
enum e : short {
    A,
    B = 2
};
"""

def test_enum_type_hook():
    src = use_hook(enum_type_hook, ENUM_TYPE_SRC)
    assert 'short' not in src
    assert ':' not in src
    assert 'enum' in src


#
# struct_func
#
STRUCT_FUNC_SRC = """
struct s {
    int func1(char a1, unsigned short a2) { return -1; }
    int x, y;
    char z;
    void func2(double b1) { return; }
};
"""

def test_struct_func_hook():
    src = use_hook(struct_func_hook, STRUCT_FUNC_SRC)
    assert 'func1' not in src
    assert 'a1' not in src
    assert 'a2' not in src

    assert 'struct' in src
    assert 'x' in src
    assert 'y' in src
    assert 'z' in src


# typedef_adder