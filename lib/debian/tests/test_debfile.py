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

import contextlib
import unittest
import os
import os.path
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from _md5 import md5   # type: ignore

from debian import arfile
from debian import debfile


try:
    # pylint: disable=unused-import
    from typing import (
        Any,
        Callable,
        Dict,
        IO,
        Iterator,
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
    TYPE_CHECKING = False

    # Fake some definitions
    if not TYPE_CHECKING:
        TypeVar = lambda t: None


CONTROL_FILE = r"""\
Package: hello
Version: 2.10-2
Architecture: amd64
Maintainer: Santiago Vila <sanvila@debian.org>
Installed-Size: 280
Depends: libc6 (>= 2.14)
Conflicts: hello-traditional
Breaks: hello-debhelper (<< 2.9)
Replaces: hello-debhelper (<< 2.9), hello-traditional
Section: devel
Priority: optional
Homepage: http://www.gnu.org/software/hello/
Description: example package based on GNU hello
 The GNU hello program produces a familiar, friendly greeting.  It
 allows non-programmers to use a classic computer science tool which
 would otherwise be unavailable to them.
 .
 Seriously, though: this is an example of how to do a Debian package.
 It is the Debian version of the GNU Project's `hello world' program
 (which is itself an example for the GNU Project).
"""


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
        subprocess.check_call(
            [
                "ar",
                "rU",
                "test.ar",
                find_test_file("test_debfile.py"),
                find_test_file("test_changelog"),
                find_test_file("test_deb822.py")
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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

    compressions = ["gztar", "bztar", "xztar", "tar"]

    # from this source package that will be included in the sample .deb
    # that is used for testing
    example_data_dir = Path("usr/share/doc/examples")
    example_data_files = [
        "test_debfile.py",
        "test_changelog",
        "test_deb822.py",
        "test_Changes",       # signed file so won't change
    ]

    @contextlib.contextmanager
    def temp_deb(self, filename='test.deb', control="gztar", data="gztar"):
        # type: (str, str, str) -> Iterator[str]
        """ Creates a test deb within a contextmanager for artefact cleanup

        :param filename:
            optionally specify the filename that will be used for the .deb
            file. If an absolute path is given, the .deb will be created
            outside of the TemporaryDirectory in which assembly is performed.
        :param control:
            optionally specify the compression format for the control member
            of the .deb file; allowable values are from
            `shutil.make_archive`: `gztar`, `bztar`, `xztar`
        :param data:
            optionally specify the compression format for the data member
            of the .deb file; allowable values are from
            `shutil.make_archive`: `gztar`, `bztar`, `xztar`
        """
        with tempfile.TemporaryDirectory(prefix="test_debfile.") as tempdir:
            tpath = Path(tempdir)
            tempdeb = str(tpath / filename)

            # the debian-binary member
            info_member = str(tpath / "debian-binary")
            with open(info_member, "wt") as fh:
                fh.write("2.0\n")

            # the data.tar member
            datapath = tpath / "data"
            examplespath = datapath / self.example_data_dir
            examplespath.mkdir(parents=True)
            for f in self.example_data_files:
                shutil.copy(find_test_file(f), str(examplespath))

            data_member = shutil.make_archive(
                str(datapath),
                data,
                root_dir=str(datapath),
            )

            # the control.tar member
            controlpath = tpath / "control"
            controlpath.mkdir()
            with open(str(controlpath / "control"), "w") as fh:
                fh.write(CONTROL_FILE)
            with open(str(controlpath / "md5sums"), "w") as fh:
                for f in self.example_data_files:
                    with open(str(examplespath / f), 'rb') as hashfh:
                        h = md5(hashfh.read()).hexdigest()
                    fh.write("%s %s\n" % (h, str(self.example_data_dir / f)))

            control_member = shutil.make_archive(
                str(controlpath),
                control,
                root_dir=str(controlpath),
            )

            # Build the .deb file using `ar`
            make_deb_command = [
                "ar", "rU", tempdeb,
                info_member,
                control_member,
                data_member,
            ]
            subprocess.check_call(
                make_deb_command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            assert os.path.exists(tempdeb)

            try:
                # provide the constructed .deb via the contextmanager
                yield tempdeb

            finally:
                # post contextmanager cleanup
                if os.path.exists(tempdeb):
                    os.unlink(tempdeb)
                # the contextmanager for the TemporaryDirectory will clean up
                # everything else that was left around

    def test_missing_members(self):
        # type: () -> None
        """ test that broken .deb files raise exceptions """
        for part in ['control.tar.gz', 'data.tar.gz']:
            with self.temp_deb() as debname:
                # break the .deb by deleting a required member
                subprocess.check_call(
                    ['ar', 'd', debname, part],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with self.assertRaises(debfile.DebError):
                    debfile.DebFile(debname)

    def test_data_compression(self):
        # type: () -> None
        """ test various compression schemes for the data member """
        for compression in self.compressions:
            with self.temp_deb(data=compression) as debname:
                deb = debfile.DebFile(debname)
                # random test on the data part, just to check that content access
                # is OK
                all_files = [os.path.normpath(f) for f in deb.data.tgz().getnames()]
                for f in self.example_data_files:
                    testfile = os.path.normpath(str(self.example_data_dir / f))
                    self.assertIn(testfile, all_files,
                        "Data part failed on compression %s" % compression)
                self.assertIn(os.path.normpath(str(self.example_data_dir)), all_files,
                    "Data part failed on compression %s" % compression)
                deb.close()

    def test_control_compression(self):
        # type: () -> None
        """ test various compression schemes for the control member """
        for compression in self.compressions:
            with self.temp_deb(data=compression) as debname:
                deb = debfile.DebFile(debname)
                # random test on the control part
                self.assertIn(
                    'control',
                    [os.path.normpath(p) for p in deb.control.tgz().getnames()],
                    "Control part failed on compression %s" % compression
                )
                self.assertIn(
                    'md5sums',
                    [os.path.normpath(p) for p in deb.control.tgz().getnames()],
                    "Control part failed on compression %s" % compression
                )
                deb.close()

    def test_data_names(self):
        # type: () -> None
        """ test for file list equality """
        with self.temp_deb() as debname:
            deb = debfile.DebFile(debname)
            tgz = deb.data.tgz()
            with os.popen("dpkg-deb --fsys-tarfile %s | tar t" % debname) as tar:
                dpkg_names = [os.path.normpath(x.strip()) for x in tar.readlines()]
            debfile_names = [os.path.normpath(name) for name in tgz.getnames()]

            # skip the root
            self.assertEqual(debfile_names[1:], dpkg_names[1:])
            deb.close()

    def test_control(self):
        # type: () -> None
        """ test for control contents equality """
        with self.temp_deb() as debname:
            with os.popen("dpkg-deb -f %s" % debname) as dpkg_deb:
                filecontrol = "".join(dpkg_deb.readlines())

            deb = debfile.DebFile(debname)
            self.assertEqual(
                not_none(deb.control.get_content("control")).decode("utf-8"),
                filecontrol)
            self.assertEqual(
                deb.control.get_content("control", encoding="utf-8"),
                filecontrol)
            deb.close()

    def test_md5sums(self):
        # type: () -> None
        """test md5 extraction from .debs"""
        with self.temp_deb() as debname:
            deb = debfile.DebFile(debname)
            md5b = deb.md5sums()
            md5 = deb.md5sums(encoding="UTF-8")

            data = [
                (self.example_data_dir / "test_Changes", "73dbb291e900d8cd08e2bb76012a3829"),
            ]
            for f, h in data:
                self.assertEqual(md5b[str(f).encode('UTF-8')], h)
                self.assertEqual(md5[str(f)], h)
            deb.close()

    def test_contextmanager(self):
        # type: () -> None
        """test use of DebFile as a contextmanager"""
        with self.temp_deb() as debname:
            with debfile.DebFile(debname) as deb:
                all_files = deb.data.tgz().getnames()
                self.assertTrue(all_files)
                self.assertTrue(deb.control.get_content("control"))

    def test_open_directly(self):
        # type: () -> None
        """test use of DebFile without the contextmanager"""
        with self.temp_deb() as debname:
            deb = debfile.DebFile(debname)
            all_files = deb.data.tgz().getnames()
            self.assertTrue(all_files)
            self.assertTrue(deb.control.get_content("control"))
            deb.close()


if __name__ == '__main__':
    unittest.main()

