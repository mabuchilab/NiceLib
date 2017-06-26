# -*- coding: utf-8 -*-
# Copyright 2016-2017 Nate Bogdanowicz
import os
import os.path
import sys
from setuptools import setup, find_packages

description = ('A package for rapidly developing "nice" Python bindings to C libraries, '
               'using `cffi`')
classifiers = [
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
]

# Load metadata from __about__.py
base_dir = os.path.dirname(__file__)
about = {}
with open(os.path.join(base_dir, 'nicelib', '__about__.py')) as f:
    exec(f.read(), about)

install_requires = ['cffi>=1.5', 'pycparser', 'future']

if sys.version_info < (3, 4):
    install_requires.append('enum34>=1.0.4')

if __name__ == '__main__':
    setup(
        name = about['__distname__'],
        version = about['__version__'],
        packages = find_packages(),
        author = about['__author__'],
        author_email = about['__email__'],
        description = description,
        long_description = '\n'.join(open("README.rst").read().splitlines()[2:]),
        url = about['__url__'],
        license = about['__license__'],
        classifiers = classifiers,
        install_requires = install_requires
    )
