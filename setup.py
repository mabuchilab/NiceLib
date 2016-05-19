# -*- coding: utf-8 -*-
# Copyright 2016 Nate Bogdanowicz
import os
import os.path
from setuptools import setup, find_packages

description = "Library with high-level drivers for lab equipment"
classifiers = [
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.6',
    'Programming Language :: Python :: 2.7',
]

# Load metadata from __about__.py
base_dir = os.path.dirname(__file__)
about = {}
with open(os.path.join(base_dir, 'nicelib', '__about__.py')) as f:
    exec(f.read(), about)

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
        install_requires = ['cffi>=1.5', 'future']
    )
