#! /usr/bin/python

# Tests for ArFile/DebFile
# Copyright (C) 2007    Stefano Zacchiroli  <zack@debian.org>
# Copyright (C) 2007    Filippo Giunchedi   <filippo@debian.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

import unittest
import os
import os.path
import re
import stat
import sys
import tempfile
import uu

import six

from debian import arfile
from debian import debfile


try:
    # pylint: disable=unused-import
    from typing import (
        Any,
        Callable,
        Dict,
        IO,
        List,
        Optional,
        Union,
        Text,
        Tuple,
        Type,
        TypeVar,
    )
except ImportError:
    # Missing types aren't important at runtime
    TypeVar = lambda t: None


def find_test_file(filename):
    # type: (str) -> str
    """ find a test file that is located within the test suite """
    return os.path.join(os.path.dirname(__file__), filename)


T = TypeVar("T")
def not_none(obj):
    # type: (Optional[T]) -> T
    assert obj is not None
    return obj


class TestArFile(unittest.TestCase):

    def setUp(self):
        # type: () -> None
        os.system(
            "ar rU test.ar %s %s %s >/dev/null 2>&1" % (
                find_test_file("test_debfile.py"),
                find_test_file("test_changelog"),
                find_test_file("test_deb822.py"))
            )
        assert os.path.exists("test.ar")
        with os.popen("ar t test.ar") as ar:
            self.testmembers = [x.strip() for x in ar.readlines()]
        self.a = arfile.ArFile("test.ar")
        self.fp = open("test.ar", "rb")

    def tearDown(self):
        # type: () -> None
        self.fp.close()
        if os.path.exists('test.ar'):
            os.unlink('test.ar')

    def test_getnames(self):
        # type: () -> None
        """ test for file list equality """
        self.assertEqual(self.a.getnames(), self.testmembers)

    def test_getmember(self):
        # type: () -> None
        """ test for each member equality """
        for member in self.testmembers:
            m = self.a.getmember(member)
            assert m
            self.assertEqual(m.name, member)

            mstat = os.stat(find_test_file(member))

            self.assertEqual(m.size, mstat[stat.ST_SIZE])
            self.assertEqual(m.owner, mstat[stat.ST_UID])
            self.assertEqual(m.group, mstat[stat.ST_GID])

    def test_file_seek(self):
        # type: () -> None
        """ test for faked seek """
        m = self.a.getmember(self.testmembers[0])

        for i in [10,100,10000,100000]:
            m.seek(i, 0)
            self.assertEqual(m.tell(), i, "failed tell()")

            m.seek(-i, 1)
            self.assertEqual(m.tell(), 0, "failed tell()")

        m.seek(0)
        self.assertRaises(IOError, m.seek, -1, 0)
        self.assertRaises(IOError, m.seek, -1, 1)
        m.seek(0)
        m.close()

    def test_file_read(self):
        # type: () -> None
        """ test for faked read """
        for m in self.a.getmembers():
            with open(find_test_file(m.name), 'rb') as f:

                for i in [10, 100, 10000]:
                    self.assertEqual(m.read(i), f.read(i))

            m.close()

    def test_file_readlines(self):
        # type: () -> None
        """ test for faked readlines """

        for m in self.a.getmembers():
            f = open(find_test_file(m.name), 'rb')

            self.assertEqual(m.readlines(), f.readlines())

            m.close()
            f.close()


class TestArFileFileObj(TestArFile):

    def setUp(self):
        # type: () -> None
        super(TestArFileFileObj, self).setUp()
        self.a = arfile.ArFile(fileobj=self.fp)

    def tearDown(self):
        # type: () -> None
        super(TestArFileFileObj, self).tearDown()


class TestDebFile(unittest.TestCase):

    test_debs = [
            find_test_file('test.deb'),
            find_test_file('test-broken.deb'),
        ]
    test_compressed_debs = [
            find_test_file('test-bz2.deb'),
            find_test_file('test-xz.deb'),
            find_test_file('test-uncompressed.deb'),
            find_test_file('test-uncompressed-ctrl.deb'),
        ]

    def setUp(self):
        # type: () -> None
        def uudecode(infile, outfile):
            # type: (str, str) -> None
            with open(infile, 'rb') as uu_deb, open(outfile, 'wb') as bin_deb:
                uu.decode(uu_deb, bin_deb)

        for package in self.test_debs + self.test_compressed_debs:
            uudecode('%s.uu' % package, package)

        self.debname = find_test_file('test.deb')
        self.d = debfile.DebFile(self.debname)

    def tearDown(self):
        # type: () -> None
        self.d.close()
        for package in self.test_debs + self.test_compressed_debs:
            os.unlink(package)

    def test_missing_members(self):
        # type: () -> None
        with self.assertRaises(debfile.DebError):
            debfile.DebFile(find_test_file('test-broken.deb'))

    def test_data_compression(self):
        # type: () -> None
        for package in self.test_compressed_debs:
            deb = debfile.DebFile(package)
            # random test on the data part, just to check that content access
            # is OK
            self.assertEqual(os.path.normpath(deb.data.tgz().getnames()[10]),
                             os.path.normpath('./usr/share/locale/bg/'),
                             "Data part failed on deb %s" % package)
            deb.close()

    def test_control_compression(self):
        # type: () -> None
        for package in self.test_compressed_debs:
            deb = debfile.DebFile(package)
            # random test on the control part
            self.assertEqual(os.path.normpath(deb.control.tgz().getnames()[1]),
                             'md5sums',
                             "Control part failed on deb %s" % package)
            deb.close()

    def test_data_names(self):
        # type: () -> None
        """ test for file list equality """
        tgz = self.d.data.tgz()
        with os.popen("dpkg-deb --fsys-tarfile %s | tar t" %
                      self.debname) as tar:
            dpkg_names = [os.path.normpath(x.strip()) for x in tar.readlines()]
        debfile_names = [os.path.normpath(name) for name in tgz.getnames()]

        # skip the root
        self.assertEqual(debfile_names[1:], dpkg_names[1:])

    def test_control(self):
        # type: () -> None
        """ test for control equality """
        with os.popen("dpkg-deb -f %s" % self.debname) as dpkg_deb:
            filecontrol = "".join(dpkg_deb.readlines())

        self.assertEqual(
            not_none(self.d.control.get_content("control")).decode("utf-8"),
            filecontrol)
        self.assertEqual(
            self.d.control.get_content("control", encoding="utf-8"),
            filecontrol)

    def test_md5sums(self):
        # type: () -> None
        """test md5 extraction from .debs"""
        md5b = self.d.md5sums()
        self.assertEqual(md5b[b'usr/bin/hello'],
                '9c1a72a78f82216a0305b6c90ab71058')
        self.assertEqual(md5b[b'usr/share/locale/zh_TW/LC_MESSAGES/hello.mo'],
                'a7356e05bd420872d03cd3f5369de42f')
        md5 = self.d.md5sums(encoding='UTF-8')
        self.assertEqual(md5[six.u('usr/bin/hello')],
                '9c1a72a78f82216a0305b6c90ab71058')
        self.assertEqual(md5[six.u('usr/share/locale/zh_TW/LC_MESSAGES/hello.mo')],
                'a7356e05bd420872d03cd3f5369de42f')

if __name__ == '__main__':
    unittest.main()

