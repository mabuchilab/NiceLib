#include <stdlib.h>

typedef struct {
    int id;
    float value;
} Item;

int add(int a, int b) {
    return a + b;
}

int subtract(int a, int b) {
    return a - b;
}


Item* create_item() {
    static int item_count = 0;
    Item* pitem = malloc(sizeof(Item));
    pitem->id = item_count++;
    pitem->value = 0;
    return pitem;
}

int item_get_id(Item *pitem) {
    return pitem->id;
}

float item_get_value(Item *pitem) {
    return pitem->value;
}

void item_set_value(Item *pitem, float value) {
    pitem->value = value;
}

int item_static_value(void) {
    return 5;
}
