typedef struct {
  int x;
} s;

void f();
void f_void(void);
void f_int(int);
void f_int_int(int, int);

void f_inta(int a);
void f_inta_intb(int a, int b);

void f_ptra(int *a);
void f_arra(int a[]);
void f_structa(s a);
void f_structptra(s* a);
