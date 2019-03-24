enum {
    anon1,
    anon2,
    anon3
};

enum TagOnly {
    tagOnlyVal1,
    tagOnlyVal2
};

typedef enum {
    typedefOnlyVal1,
    typedefOnlyVal2
} TypedefOnly;

typedef enum EnumTag {
    bothVal1,
    bothVal2
} EnumType;

typedef enum {
    multiVal1,
    multiVal2
} EnumA, EnumB, EnumC;

typedef int int2;
typedef int2 int3;
