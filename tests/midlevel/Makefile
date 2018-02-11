sharedlibs: libfoo

libfoo:
	$(CC) -c -Wall -Werror -fpic foo.c
	$(CC) -shared -o libfoo.so foo.o

clean:
	rm foo.o libfoo.so _foolib.py
