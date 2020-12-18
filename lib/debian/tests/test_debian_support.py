#!/usr/bin/python

# Copyright (C) 2005 Florian Weimer <fw@deneb.enyo.de>
# Copyright (C) 2006-2007 James Westby <jw+debian@jameswestby.net>
# Copyright (C) 2010 John Wright <jsw@debian.org>
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

from __future__ import absolute_import

import gzip
import os
import os.path
import six
import sys
import tempfile
import re

import unittest

from debian import debian_support
from debian.debian_support import *


try:
    # pylint: disable=unused-import
    from typing import (
        Any,
        List,
        Optional,
    )
except ImportError:
    # Missing types aren't important at runtime
    pass


def find_test_file(filename):
    # type: (str) -> str
    """ find a test file that is located within the test suite """
    return os.path.abspath(os.path.join(os.path.dirname(__file__), filename))


class VersionTests(unittest.TestCase):
    """Tests for AptPkgVersion and NativeVersion classes in debian_support"""

    def setUp(self):
        # type: () -> None
        if debian_support._have_apt_pkg:
            self.test_classes = [AptPkgVersion, NativeVersion]
        else:
            self.test_classes = [NativeVersion]

    def _test_version(self, full_version, epoch, upstream, debian):
        # type: (str, Optional[str], str, Optional[str]) -> None
        for cls in self.test_classes:
            v = cls(full_version)
            self.assertEqual(v.full_version, full_version,
                             "%s: full_version broken" % cls)
            self.assertEqual(v.epoch, epoch, "%s: epoch broken" % cls)
            self.assertEqual(v.upstream_version, upstream,
                             "%s: upstream_version broken" % cls)
            self.assertEqual(v.debian_revision, debian,
                             "%s: debian_revision broken" % cls)

    def testversions(self):
        # type: () -> None
        self._test_version('1:1.4.1-1', '1', '1.4.1', '1')
        self._test_version('7.1.ds-1', None, '7.1.ds', '1')
        self._test_version('10.11.1.3-2', None, '10.11.1.3', '2')
        self._test_version('4.0.1.3.dfsg.1-2', None, '4.0.1.3.dfsg.1', '2')
        self._test_version('0.4.23debian1', None, '0.4.23debian1', None)
        self._test_version('1.2.10+cvs20060429-1', None,
                '1.2.10+cvs20060429', '1')
        self._test_version('0.2.0-1+b1', None, '0.2.0', '1+b1')
        self._test_version('4.3.90.1svn-r21976-1', None,
                '4.3.90.1svn-r21976', '1')
        self._test_version('1.5+E-14', None, '1.5+E', '14')
        self._test_version('20060611-0.0', None, '20060611', '0.0')
        self._test_version('0.52.2-5.1', None, '0.52.2', '5.1')
        self._test_version('7.0-035+1', None, '7.0', '035+1')
        self._test_version('1.1.0+cvs20060620-1+2.6.15-8', None,
            '1.1.0+cvs20060620-1+2.6.15', '8')
        self._test_version('1.1.0+cvs20060620-1+1.0', None,
                '1.1.0+cvs20060620', '1+1.0')
        self._test_version('4.2.0a+stable-2sarge1', None, '4.2.0a+stable',
                           '2sarge1')
        self._test_version('1.8RC4b', None, '1.8RC4b', None)
        self._test_version('0.9~rc1-1', None, '0.9~rc1', '1')
        self._test_version('2:1.0.4+svn26-1ubuntu1', '2', '1.0.4+svn26',
                           '1ubuntu1')
        self._test_version('2:1.0.4~rc2-1', '2', '1.0.4~rc2', '1')
        for cls in self.test_classes:
            self.assertRaises(
                ValueError, cls, 'a1:1.8.8-070403-1~priv1')

    def test_version_updating(self):
        # type: () -> None
        for cls in self.test_classes:
            v = cls('1:1.4.1-1')

            v.debian_version = '2'
            self.assertEqual(v.debian_version, '2')
            self.assertEqual(v.full_version, '1:1.4.1-2')

            v.upstream_version = '1.4.2'
            self.assertEqual(v.upstream_version, '1.4.2')
            self.assertEqual(v.full_version, '1:1.4.2-2')

            v.epoch = '2'
            self.assertEqual(v.epoch, '2')
            self.assertEqual(v.full_version, '2:1.4.2-2')

            self.assertEqual(str(v), v.full_version)

            v.full_version = '1:1.4.1-1'
            self.assertEqual(v.full_version, '1:1.4.1-1')
            self.assertEqual(v.epoch, '1')
            self.assertEqual(v.upstream_version, '1.4.1')
            self.assertEqual(v.debian_version, '1')

    @staticmethod
    def _get_truth_fn(cmp_oper):
        # type: (str) -> Any
        if cmp_oper == "<":
            return lambda a, b: a < b
        elif cmp_oper == "<=":
            return lambda a, b: a <= b
        elif cmp_oper == "==":
            return lambda a, b: a == b
        elif cmp_oper == ">=":
            return lambda a, b: a >= b
        elif cmp_oper == ">":
            return lambda a, b: a > b
        else:
            raise ValueError("invalid operator %s" % cmp_oper)

    def _test_comparison(self, v1_str, cmp_oper, v2_str):
        # type: (str, str, str) -> None
        """Test comparison against all combinations of Version classes

        This is does the real work for test_comparisons.
        """

        if debian_support._have_apt_pkg:
            test_class_tuples = [
                (AptPkgVersion, AptPkgVersion),
                (AptPkgVersion, NativeVersion),
                (NativeVersion, AptPkgVersion),
                (NativeVersion, NativeVersion),
                (str, AptPkgVersion), (AptPkgVersion, str),
                (str, NativeVersion), (NativeVersion, str),
            ]
        else:
            test_class_tuples = [
                 (NativeVersion, NativeVersion),
                 (str, NativeVersion), (NativeVersion, str),
            ]

        for (cls1, cls2) in test_class_tuples:
            v1 = cls1(v1_str)
            v2 = cls2(v2_str)
            truth_fn = self._get_truth_fn(cmp_oper)
            self.assertTrue(truth_fn(v1, v2) == True,
                            "%r %s %r != True" % (v1, cmp_oper, v2))

    def test_comparisons(self):
        # type: () -> None
        """Test comparison against all combinations of Version classes"""

        self._test_comparison('0', '<', 'a')
        self._test_comparison('1.0', '<', '1.1')
        self._test_comparison('1.2', '<', '1.11')
        self._test_comparison('1.0-0.1', '<', '1.1')
        self._test_comparison('1.0-0.1', '<', '1.0-1')
        self._test_comparison('1.0', '==', '1.0')
        self._test_comparison('1.0-0.1', '==', '1.0-0.1')
        self._test_comparison('1:1.0-0.1', '==', '1:1.0-0.1')
        self._test_comparison('1:1.0', '==', '1:1.0')
        self._test_comparison('1.0-0.1', '<', '1.0-1')
        self._test_comparison('1.0final-5sarge1', '>', '1.0final-5')
        self._test_comparison('1.0final-5', '>', '1.0a7-2')
        self._test_comparison('0.9.2-5', '<',
                              '0.9.2+cvs.1.0.dev.2004.07.28-1.5')
        self._test_comparison('1:500', '<', '1:5000')
        self._test_comparison('100:500', '>', '11:5000')
        self._test_comparison('1.0.4-2', '>', '1.0pre7-2')
        self._test_comparison('1.5~rc1', '<', '1.5')
        self._test_comparison('1.5~rc1', '<', '1.5+b1')
        self._test_comparison('1.5~rc1', '<', '1.5~rc2')
        self._test_comparison('1.5~rc1', '>', '1.5~dev0')


class ReleaseTests(unittest.TestCase):
    """Tests for debian_support.Release"""

    def test_comparison(self):
        # type: () -> None
        self.assertLess(intern_release('buzz'), intern_release('hamm'))
        self.assertLess(intern_release('sarge'), intern_release('etch'))
        self.assertLess(intern_release('lenny'), intern_release('squeeze'))


class HelperRoutineTests(unittest.TestCase):
    """Tests for various debian_support helper routines"""

    def test_read_lines_sha1(self):
        # type: () -> None
        empty = []  # type: List[bytes]
        self.assertEqual(read_lines_sha1(empty),
                         'da39a3ee5e6b4b0d3255bfef95601890afd80709')
        self.assertEqual(read_lines_sha1(['1\n', '23\n']),
                         '14293c9bd646a15dc656eaf8fba95124020dfada')

    def test_patch_lines(self):
        # type: () -> None
        file_a = ["%d\n" % x for x in range(1, 18)]
        file_b = ['0\n', '1\n', '<2>\n', '<3>\n', '4\n', '5\n', '7\n', '8\n',
                  '11\n', '12\n', '<13>\n', '14\n', '15\n', 'A\n', 'B\n',
                  'C\n', '16\n', '17\n',]
        patch = ['15a\n', 'A\n', 'B\n', 'C\n', '.\n', '13c\n', '<13>\n', '.\n',
                 '9,10d\n', '6d\n', '2,3c\n', '<2>\n', '<3>\n', '.\n', '0a\n',
                 '0\n', '.\n']
        patch_lines(file_a, patches_from_ed_script(patch))
        self.assertEqual(''.join(file_b), ''.join(file_a))

    def test_patch_lines_bytes(self):
        # type: () -> None
        file_a = [b"%d\n" % x for x in range(1, 18)]
        file_b = [b'0\n', b'1\n', b'<2>\n', b'<3>\n', b'4\n', b'5\n', b'7\n', b'8\n',
                  b'11\n', b'12\n', b'<13>\n', b'14\n', b'15\n', b'A\n', b'B\n',
                  b'C\n', b'16\n', b'17\n',]
        patch = [b'15a\n', b'A\n', b'B\n', b'C\n', b'.\n', b'13c\n', b'<13>\n', b'.\n',
                 b'9,10d\n', b'6d\n', b'2,3c\n', b'<2>\n', b'<3>\n', b'.\n', b'0a\n',
                 b'0\n', b'.\n']
        patch_re_bytes = re.compile(b"^(\\d+)(?:,(\\d+))?([acd])$")
        patch_lines(file_a, patches_from_ed_script(patch, re_cmd=patch_re_bytes))
        self.assertEqual(b''.join(file_b), b''.join(file_a))


class PdiffTests(unittest.TestCase):
    """ Tests for functions dealing with pdiffs """

    def test_download_gunzip_lines(self):
        # type: () -> None
        filename = find_test_file('test_Packages.diff/test_Packages.1.gz')
        lines = download_gunzip_lines("file://" + filename)
        self.assertTrue(len(lines))

    def test_update_file(self):
        # type: () -> None
        # The original file
        original = find_test_file('test_Packages')
        # The 'remote' location from which the update will be made
        remote = find_test_file('test_Packages')
        # A correctly updated file for comparison
        updated = find_test_file('test_Packages_pdiff_updated')

        try:
            # Make a copy of the original file so it can be updated
            fd, copy = tempfile.mkstemp()
            fp = os.fdopen(fd, 'w')
            with open(original, 'r') as fh:
                fp.write(fh.read())
            fp.close()

            # run the update
            update_file("file://" + remote, copy, verbose=False)

            # check that the updated copy is the same as the known-good file
            with open(copy) as oh, open(updated) as uh:
                self.assertEqual(oh.read(), uh.read())

        finally:
            os.remove(copy)


class PackageFileTests(unittest.TestCase):
    """ Tests for functions dealing with Packages and Sources """

    def assertType(self, var_, type_):
        # type: (Any, Any) -> None
        """Check that the type is as expected
        """
        self.assertTrue(isinstance(var_, type_))

    def test_read_file(self):
        # type: () -> None
        # test_Packages is ASCII
        packfile = find_test_file('test_Packages')
        pf = debian_support.PackageFile(packfile)
        pflist = list(pf)
        self.assertEqual(len(pflist), 3)
        pf.file.close()

        # test_Sources is UTF-8
        # test for bad decoding, #928655
        packfile = find_test_file('test_Sources')
        pf = debian_support.PackageFile(packfile)
        pflist = list(pf)
        self.assertEqual(len(pflist), 4)
        pf.file.close()

    def test_read_fileobj(self):
        # type: () -> None
        packfile = find_test_file('test_Packages')
        with open(packfile, 'rb') as fhbin:
            pf = debian_support.PackageFile('ignored', file_obj=fhbin)
            pflist = list(pf)
            self.assertEqual(len(pflist), 3)
            self.assertType(pflist[0][0][1], six.string_types)
        with open(packfile, 'rt') as fhtext:
            pf = debian_support.PackageFile('ignored', file_obj=fhtext)
            pflist = list(pf)
            self.assertEqual(len(pflist), 3)
            self.assertType(pflist[0][0][1], six.string_types)


if __name__ == "__main__":
    unittest.main()
