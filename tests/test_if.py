import pytest
from nicelib.process import Parser


@pytest.mark.parametrize("num,result", [
    (1, "20"),
    (2, "40"),
    (3, "60"),
    (0, "60"),
])
def test_if(num, result):
    parser = Parser("""
        #define x {}

        #if x == 1
            #define y 20
        #elif x == 2
            #define y 40
        #else
            #define y 60
        #endif
    """.format(num))
    parser.parse()
    print(parser.macros['y'].body_str())
    assert parser.macros['y'].body_str() == result


@pytest.mark.parametrize("num,result", [
    (1, "5"),
    (2, "5"),
    (3, "5"),
    (0, "5"),
])
def test_nested_if(num, result):
    parser = Parser("""
        #define x {}
        #define y 5

        #if 0
            #if x == 1
                #define y 20
            #elif x == 2
                #define y 40
            #else
                #define y 60
            #endif
        #endif
    """.format(num))
    parser.parse()
    print(parser.macros['y'].body_str())
    assert parser.macros['y'].body_str() == result


@pytest.mark.parametrize("num,result", [
    (1, "20"),
    (2, "40"),
    (3, "60"),
    (0, "60"),
])
def test_nested_if2(num, result):
    parser = Parser("""
        #define x {}
        #define y 0

        #if 1
            #if x == 1
                #define y 20
            #elif x == 2
                #define y 40
            #else
                #define y 60
            #endif
        #endif
    """.format(num))
    parser.parse()
    print(parser.macros['y'].body_str())
    assert parser.macros['y'].body_str() == result


@pytest.mark.parametrize("num,result", [
    (1, ("20", "0",  "0")),
    (2, ("0",  "40", "0")),
    (3, ("0",  "0",  "60")),
    (0, ("0",  "0",  "60")),
])
def test_if_each(num, result):
    parser = Parser("""
        #define a {}
        #define x 0
        #define y 0
        #define z 0

        #if a == 1
            #define x 20
        #elif a == 2
            #define y 40
        #else
            #define z 60
        #endif
    """.format(num))
    parser.parse()
    print(parser.macros['x'].body_str())
    print(parser.macros['y'].body_str())
    print(parser.macros['z'].body_str())
    assert parser.macros['x'].body_str() == result[0]
    assert parser.macros['y'].body_str() == result[1]
    assert parser.macros['z'].body_str() == result[2]


@pytest.mark.parametrize("num,result", [
    (1, ("20", "0",  "0")),
    (2, ("0",  "0",  "60")),
    (3, ("0",  "0",  "60")),
    (0, ("0",  "0",  "60")),
])
def test_if_each2(num, result):
    parser = Parser("""
        #define a {}
        #define x 0
        #define y 0
        #define z 0

        #if a == 1
            #define x 20
        #elif a == 1
            #define y 40
        #else
            #define z 60
        #endif
    """.format(num))
    parser.parse()
    print(parser.macros['x'].body_str())
    print(parser.macros['y'].body_str())
    print(parser.macros['z'].body_str())
    assert parser.macros['x'].body_str() == result[0]
    assert parser.macros['y'].body_str() == result[1]
    assert parser.macros['z'].body_str() == result[2]
