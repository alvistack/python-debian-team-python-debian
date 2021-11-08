#!/usr/bin/python

# Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from setuptools import setup
import sys

sys.path.insert(0, 'lib')
import debian

description = """\
This package provides Python 3 modules that abstract many formats of Debian
related files. Currently handled are:

  * Debtags information (debian.debtags module)
  * debian/changelog (debian.changelog module)
  * Packages files, pdiffs (debian.debian_support module)
  * Control files of single or multiple RFC822-style paragraphs, e.g.
    debian/control, .changes, .dsc, Packages, Sources, Release, etc.
    (debian.deb822 module)
  * Raw .deb and .ar files, with (read-only) access to contained
    files and meta-information
"""

setup(
    name='python-debian',
    version=debian.__version__,
    description='Debian package related modules',
    long_description=description,
    license='GPL-2+',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: DFSG approved',
        'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)',
        'Operating System :: POSIX',
        'Programming Language :: Python',
    ],
    platforms=['any'],
    url='https://salsa.debian.org/python-debian-team/python-debian',
    package_dir={'': 'lib'},
    packages=[
        'debian',
        'debian_bundle',
        'debian._deb822_repro',
    ],
    package_data={'debian': ['py.typed']},
    py_modules=['deb822'],
    python_requires='>=3.5',
    maintainer='Debian python-debian Maintainers',
    maintainer_email='pkg-python-debian-maint@lists.alioth.debian.org',
    install_requires=['chardet'],
    test_suite='debian.tests',
)
