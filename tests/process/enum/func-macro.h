enum {
    EnumA = 1,
    EnumB,
    EnumC = 0
};

enum {
#define CALC(v) ((Enum##v) << 8)
    X = CALC(A),
    Y = CALC(B),
    Z = CALC(C)
#undef CALC
};
