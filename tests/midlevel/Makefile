sharedlibs: libfoo libbar

libfoo:
	$(CC) -c -Wall -Werror -fpic foo.c
	$(CC) -shared -o libfoo.so foo.o

libbar:
	$(CC) -c -Wall -Werror -fpic bar.c
	$(CC) -shared -o libbar.so bar.o

clean:
	rm foo.o libfoo.so _foolib.py libbar.so _barlib.py _bar2lib.py
