from util import local_fpath
from nicelib.process import (lexer, add_line_directive_hook, declspec_hook, extern_c_hook,
                             enum_type_hook, struct_func_hook, vc_pragma_hook, asm_hook)


def use_hook(hook, src):
    """Takes and return a header source string"""
    tokens = lexer.lex(src)
    tokens = hook(tokens)
    return ''.join(t.string for t in tokens)


# add_line_directive

#
# declspec
#
DECLSPEC_SRC = """
__declspec(dllimport) int xx;
__declspec(dllexport) float yy;
__declspec(noreturn) void func(void);
__declspec(deprecated(_Text)) int blah();
"""

def test_declspec_hook():
    src = use_hook(declspec_hook, DECLSPEC_SRC)
    assert '__declspec' not in src
    assert 'dllimport' not in src
    assert 'dllexport' not in src
    assert 'noreturn' not in src
    assert 'xx' in src
    assert 'yy' in src
    assert 'void' in src
    assert 'func' in src
    assert 'blah' in src


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



#
# vc_pragma
#
VC_PRAGMA_SRC = """
#define OPEN    __pragma(pack(push, 8))
#define CLOSE   __pragma(pack(pop))

OPEN
typedef unsigned int size_t;
CLOSE
"""

def test_vc_pragma_hook():
    src = use_hook(vc_pragma_hook, VC_PRAGMA_SRC)
    assert '__pragma' not in src
    assert '(' not in src
    assert ')' not in src
    assert 'pack' not in src


#
# asm
#
ASM_SRC = """
_asm int 0xff;

int func(val) {
    __asm {
        mov  ecx, val
        shl  eax, cl
    }
}

_asm mov ecx, 4     _asm mov edx, 2

_asm {
    sar  edx, cl
}
"""

def test_asm_hook():
    src = use_hook(asm_hook, ASM_SRC)
    assert 'asm' not in src
    assert '0xff' not in src
    assert 'ecx' not in src
    assert 'func' in src
