sharedlibs: libfoo

libfoo:
	$(CC) -c -Wall -Werror -fpic foo.c
	$(CC) -shared -o libfoo.so foo.o


libenum:
	$(CC) -c -Wall -Werror -fpic enum.c
	$(CC) -shared -o libenum.so enum.o


clean:
	rm foo.o libfoo.so _foolib.py
	rm enum.o libenum.so _enumlib.py
