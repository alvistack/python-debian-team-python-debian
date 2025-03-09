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
import os
import os.path
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest

from _md5 import md5   # type: ignore

from debian import arfile
from debian import debfile


from typing import (
    Any,
    Callable,
    Dict,
    Generator,
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



# Only run tests that rely on ar to make archives if it installed.
_ar_path = shutil.which('ar') or ""
# Only run tests that rely on zstd to make archives if it installed.
_zstd_path = shutil.which('zstd') or ""
# Only run tests that rely on dpkg-deb to make archives if it installed.
_dpkg_deb_path = shutil.which('dpkg-deb') or ""


# Deterministic tests are good; automatically skipping tests because optional
# dependencies are not available is a way of accidentally missing problems.
# Here, we control whether missing dependencies result in skipping tests
# or if instead, missing dependencies cause test failures.
#
# FORBID_MISSING_AR:
#   any non-empty value for the environment variable FORBID_MISSING_AR
#   will mean that tests fail if ar (from binutils) can't be found
FORBID_MISSING_AR = os.environ.get("FORBID_MISSING_AR", None)
#
# FORBID_MISSING_ZSTD:
#   any non-empty value for the environment variable FORBID_MISSING_ZSTD
#   will mean that tests fail if zstd (from zstd) can't be found
FORBID_MISSING_ZSTD = os.environ.get("FORBID_MISSING_ZSTD", None)
#
# FORBID_MISSING_DPKG_DEB:
#   any non-empty value for the environment variable FORBID_MISSING_DPKG_DEB
#   will mean that tests fail if dpkg-deb (from dpkg) can't be found
FORBID_MISSING_DPKG_DEB = os.environ.get("FORBID_MISSING_DPKG_DEB", None)


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


def find_test_file(filename: str) -> str:
    """ find a test file that is located within the test suite """
    return os.path.join(os.path.dirname(__file__), filename)


class TestToolsInstalled:

    def test_ar_installed(self) -> None:
        """ test that ar is available from binutils (e.g. /usr/bin/ar) """
        # If test suite is running in FORBID_MISSING_AR mode where
        # having ar is mandatory, explicitly include a failing test to
        # highlight this problem.
        if FORBID_MISSING_AR and not _ar_path:
            pytest.fail("Required ar executable is not installed (tests run in FORBID_MISSING_AR mode)")

    def test_dpkg_deb_installed(self) -> None:
        """ test that dpkg-deb is available from dpkg (e.g. /usr/bin/dpkg-deb) """
        # If test suite is running in FORBID_MISSING_DPKG_DEB mode where
        # having dpkg-deb is mandatory, explicitly include a failing test to
        # highlight this problem.
        if FORBID_MISSING_DPKG_DEB and not _dpkg_deb_path:
            pytest.fail("Required dpkg-deb executable is not installed (tests run in FORBID_MISSING_DPKG_DEB mode)")

    def test_zstd_installed(self) -> None:
        """ test that zstd is available from zstd (e.g. /usr/bin/zstd) """
        # If test suite is running in FORBID_MISSING_ZSTD mode where
        # having zstd is mandatory, explicitly include a failing test to
        # highlight this problem.
        if FORBID_MISSING_ZSTD and not _zstd_path:
            pytest.fail("Required zstd executable is not installed (tests run in FORBID_MISSING_ZSTD mode)")


@pytest.mark.skipif(not _ar_path, reason="ar not installed")
class TestArFile:
    fromfp = False

    @pytest.fixture()
    def sample_archive(self) -> Generator[None, None, None]:
        subprocess.check_call(
            [
                _ar_path,
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
        self.fp = open("test.ar", "rb")
        if self.fromfp:
            self.a = arfile.ArFile(fileobj=self.fp)
        else:
            self.a = arfile.ArFile("test.ar")

        yield

        if hasattr(self, 'fp'):
            self.fp.close()
        if os.path.exists('test.ar'):
            os.unlink('test.ar')

    def test_getnames(self, sample_archive):
        # type: (None) -> None
        """ test for file list equality """
        assert self.a.getnames() == self.testmembers

    def test_getmember(self, sample_archive):
        # type: (None) -> None
        """ test for each member equality """
        for member in self.testmembers:
            m = self.a.getmember(member)
            assert m
            assert m.name == member

            mstat = os.stat(find_test_file(member))

            assert m.size == mstat[stat.ST_SIZE]
            assert m.owner == mstat[stat.ST_UID]
            assert m.group == mstat[stat.ST_GID]

    def test_file_seek(self, sample_archive):
        # type: (None) -> None
        """ test for faked seek """
        m = self.a.getmember(self.testmembers[0])

        for i in [10,100,10000,100000]:
            m.seek(i, 0)
            assert m.tell() == i, "failed tell()"

            m.seek(-i, 1)
            assert m.tell() == 0, "failed tell()"

        m.seek(0)
        with pytest.raises(IOError):
            m.seek(-1, 0)
        with pytest.raises(IOError):
            m.seek(-1, 1)
        m.seek(0)
        m.close()

    def test_file_read(self, sample_archive):
        # type: (None) -> None
        """ test for faked read """
        for m in self.a.getmembers():
            with open(find_test_file(m.name), 'rb') as f:

                for i in [10, 100, 10000]:
                    assert m.read(i) == f.read(i)

            m.close()

    def test_file_readlines(self, sample_archive):
        # type: (None) -> None
        """ test for faked readlines """

        for m in self.a.getmembers():
            f = open(find_test_file(m.name), 'rb')

            assert m.readlines() == f.readlines()

            m.close()
            f.close()


@pytest.mark.skipif(not _ar_path, reason="ar not installed")
class TestArFileFileObj(TestArFile):
    fromfp = True


def _make_archive(dir_path: str, compression: str) -> str:
    """ Create an archive from a directory with a given compression algorithm.

    :returns: the path to the created archive
    """

    if compression == "zsttar":
        if not _zstd_path:
            if FORBID_MISSING_ZSTD:
                pytest.fail("Required zstd is not installed (tests run in FORBID_MISSING_ZSTD mode")
            pytest.skip("zstd not installed")
        uncompressed_archive = shutil.make_archive(
            dir_path,
            "tar",
            root_dir=dir_path,
        )
        archive = uncompressed_archive + ".zst"
        with open(uncompressed_archive) as input:
            proc =subprocess.Popen([_zstd_path, "-q", "-o", archive], stdin=input)
            assert(proc.wait() == 0)
        os.remove(uncompressed_archive)
    else:
        archive = shutil.make_archive(
            dir_path,
            compression,
            root_dir=dir_path,
        )
    return archive


compressions = ["gztar", "bztar", "xztar", "tar", "zsttar"]

@pytest.mark.skipif(not _ar_path, reason="ar not installed")
class TestDebFile:

    # from this source package that will be included in the sample .deb
    # that is used for testing
    example_data_dir = Path("usr/share/doc/examples")
    example_data_files = [
        "test_debfile.py",
        "test_changelog",
        "test_deb822.py",
        "test_Changes",       # signed file so won't change
    ]
    # location for symlinks in the archive, relative to the example dir
    link_data_dirs = [
        "../links",
        "/var/tests",
    ]

    @pytest.fixture()
    def sample_deb_control(self, request: Any) -> Generator[str, None, None]:
        control = getattr(request, "param", "gztar")
        yield from self._generate_deb(control=control)

    @pytest.fixture()
    def sample_deb_data(self, request: Any) -> Generator[str, None, None]:
        data = getattr(request, "param", "gztar")
        yield from self._generate_deb(data=data)

    @pytest.fixture()
    def sample_deb_binnmu(self, request: Any) -> Generator[str, None, None]:
        def control_binnmu() -> str:
            return CONTROL_FILE.replace(
                "Version",
                "Source: hellosrc (1.2.3)\nVersion"
            )
        yield from self._generate_deb(control_generator=control_binnmu)

    @pytest.fixture()
    def sample_deb(self, request: Any) -> Generator[str, None, None]:
        config = getattr(request, "param", (None, None, None))
        control = config[0] or 'gztar'
        data = config[1] or 'gztar'
        control_generator = config[2] or None
        yield from self._generate_deb(
            control=control,
            data=data,
            control_generator=control_generator
        )

    def _generate_deb(
        self,
        filename: str = "test.deb",
        control: str = "gztar",
        data: str = "gztar",
        control_generator: Optional[Callable[[], str]] = None
    ) -> Generator[str, None, None]:
        """ Creates a test deb within a contextmanager for artefact cleanup

        :param filename:
            optionally specify the filename that will be used for the .deb
            file. If an absolute path is given, the .deb will be created
            outside of the TemporaryDirectory in which assembly is performed.
        :param control:
            optionally specify the compression format for the control member
            of the .deb file; allowable values are from
            `shutil.make_archive`: `gztar`, `bztar`, `xztar`, `zsttar`
        :param data:
            optionally specify the compression format for the data member
            of the .deb file; allowable values are from
            `shutil.make_archive`: `gztar`, `bztar`, `xztar`, `zsttar`
        """
        control_generator = control_generator or (lambda: CONTROL_FILE)
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

            # Make some symlinks for testing
            # a) symlink within a directory (relative path)
            dest = Path(self.example_data_files[0])
            link = Path(examplespath / ("link_" + self.example_data_files[0]))
            link.symlink_to(dest)

            # b) symlinks traversing directories
            for d in self.link_data_dirs:
                # dest dir for links
                linkspath = str(self.example_data_dir / d)
                tmplinkpath = Path(datapath) / (linkspath if not linkspath.startswith("/") else linkspath[1:])
                tmplinkpath.mkdir(parents=True)

                # Find the correct path for the symlink according to Policy
                # policy says to use relative paths unless the path traverses /
                if d.startswith("/"):
                    # it traverses root so use the absolute path
                    destpath = Path("/") / self.example_data_dir
                else:
                    # relative path is acceptable
                    # CRUFT: python < 3.6 doesn't support pathlib in os.path
                    destpath = Path(os.path.relpath(str(self.example_data_dir), linkspath))
                # finally, the destination where the link is supposed to point to
                dest = destpath / self.example_data_files[0]
                # and the actual filesystem location of the link
                # CRUFT: for python >= 3.6 this can be done with .resolve()
                link = Path(os.path.normpath(str(tmplinkpath / self.example_data_files[0])))
                link.symlink_to(dest)

                # c) also make a symlink to a directory
                # CRUFT: for python >= 3.6 this can be done with .resolve()
                link = Path(os.path.normpath(str(tmplinkpath / "dirlink")))
                link.symlink_to(destpath)

            data_member = _make_archive(str(datapath), data)

            # the control.tar member
            controlpath = tpath / "control"
            controlpath.mkdir()
            with open(str(controlpath / "control"), "w") as fh:
                fh.write(control_generator())
            with open(str(controlpath / "md5sums"), "w") as fh:
                for f in self.example_data_files:
                    with open(str(examplespath / f), 'rb') as hashfh:
                        h = md5(hashfh.read()).hexdigest()
                    fh.write("%s %s\n" % (h, str(self.example_data_dir / f)))

            control_member = _make_archive(str(controlpath), control)

            # Build the .deb file using `ar`
            make_deb_command = [
                _ar_path, "rU", tempdeb,
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

    @pytest.mark.parametrize('part', ['control.tar.gz', 'data.tar.gz'])
    def test_missing_members(self, sample_deb: str, part: str) -> None:
        """ test that broken .deb files raise exceptions """
        # break the .deb by deleting a required member
        subprocess.check_call(
            [_ar_path, 'd', sample_deb, part],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with pytest.raises(debfile.DebError):
            debfile.DebFile(sample_deb)

    @pytest.mark.parametrize("sample_deb_data", compressions, indirect=["sample_deb_data"])
    def test_data_compression(self, sample_deb_data: str) -> None:
        """ test various compression schemes for the data member """
        with debfile.DebFile(sample_deb_data) as deb:
            # random test on the data part, just to check that content access
            # is OK
            all_files = [os.path.normpath(f) for f in deb.data.tgz().getnames()]
            for f in self.example_data_files:
                testfile = os.path.normpath(str(self.example_data_dir / f))
                assert testfile in all_files, \
                    "Data part failed on compression"
            assert os.path.normpath(str(self.example_data_dir)) in all_files, \
                "Data part failed on compression"

    @pytest.mark.parametrize("sample_deb_control", compressions, indirect=["sample_deb_control"])
    def test_control_compression(self, sample_deb_control: str) -> None:
        """ test various compression schemes for the control member """
        with debfile.DebFile(sample_deb_control) as deb:
            # random test on the control part
            assert 'control' in \
                [os.path.normpath(p) for p in deb.control.tgz().getnames()], \
                "Control part failed on compression"
            assert 'md5sums' in \
                [os.path.normpath(p) for p in deb.control.tgz().getnames()], \
                "Control part failed on compression"

    @pytest.mark.skipif(not _dpkg_deb_path, reason="dpkg-deb not installed")
    def test_data_names(self, sample_deb: str) -> None:
        """ test for file list equality """
        with debfile.DebFile(sample_deb) as deb:
            tgz = deb.data.tgz()
            with os.popen("dpkg-deb --fsys-tarfile %s | tar t" % sample_deb) as tar:
                dpkg_names = [os.path.normpath(x.strip()) for x in tar.readlines()]
            debfile_names = [os.path.normpath(name) for name in tgz.getnames()]

            # skip the root
            assert debfile_names[1:] == dpkg_names[1:]

    def _test_file_contents(self, debname, debfilename, origfilename, modes=None, follow_symlinks=False):
        # type: (str, Union[str, Path], Union[str, Path], Optional[List[str]], bool) -> None
        """ helper function to test that the deb file has the right contents """
        modes = modes or ["rb", "rt"]
        for mode in modes:
            with debfile.DebFile(debname) as deb:
                with open(origfilename, mode) as fh:
                    origdata = fh.read()
                encoding = None if not "t" in mode else "UTF-8"
                for prefix in "", "./":
                    dfh = deb.data.get_file(prefix + str(debfilename), encoding=encoding, follow_symlinks=follow_symlinks)
                    debdata = dfh.read()
                    assert origdata == debdata
                    dfh.close()

    def test_data_has_file(self, sample_deb: str) -> None:
        """ test for round-trip of a data file """
        # also test some variations on how the root directory is stored
        with debfile.DebFile(sample_deb) as deb:
            debdatafile = str(self.example_data_dir / self.example_data_files[-1])
            assert deb.data.has_file(debdatafile)
            assert deb.data.has_file("./" + debdatafile)

            assert deb.data.has_file("/")
            assert deb.data.has_file("./")
            assert deb.data.has_file(".")

            assert not deb.data.has_file("/usr/share/doc/nosuchfile")
            assert not deb.data.has_file("/nosuchdir/nosuchfile")

    def test_data_has_file_symlinks(self, sample_deb: str) -> None:
        """ test for round-trip of a data file """
        def path(*args):
            # type: (Union[str, Path]) -> str
            return os.path.normpath(os.path.join(
                str(self.example_data_dir), *args
            ))

        with debfile.DebFile(sample_deb) as deb:
            # link to file in same directory
            debdatafile = str(self.example_data_dir / ( "link_" + self.example_data_files[0]))
            assert deb.data.has_file(debdatafile)

            # link to file in different directory
            debdatafile = path(self.link_data_dirs[0], self.example_data_files[0])
            assert deb.data.has_file(debdatafile, follow_symlinks=False)

            debdatafile = path(self.link_data_dirs[0], self.example_data_files[0])
            assert deb.data.has_file(debdatafile, follow_symlinks=True)

            # link to file in different dir traversing /
            debdatafile = path(self.link_data_dirs[1], self.example_data_files[0])
            assert deb.data.has_file(debdatafile, follow_symlinks=False)

            debdatafile = path(self.link_data_dirs[1], self.example_data_files[0])
            assert deb.data.has_file(debdatafile, follow_symlinks=True)

            # file beyond a directory symlink
            debdatafile = path(self.link_data_dirs[0], "dirlink", self.example_data_files[0])
            assert not deb.data.has_file(debdatafile, follow_symlinks=False)

            debdatafile = path(self.link_data_dirs[0], "dirlink", self.example_data_files[0])
            assert deb.data.has_file(debdatafile, follow_symlinks=True)

            # file beyond a directory symlink traversing /
            debdatafile = path(self.link_data_dirs[1], "dirlink", self.example_data_files[0])
            assert not deb.data.has_file(debdatafile, follow_symlinks=False)

            debdatafile = path(self.link_data_dirs[1], "dirlink", self.example_data_files[0])
            assert deb.data.has_file(debdatafile, follow_symlinks=True)

            # non-existent files and directories
            assert not deb.data.has_file("/usr/share/doc/nosuchfile", follow_symlinks=False)
            assert not deb.data.has_file("/nosuchdir/nosuchfile", follow_symlinks=True)
            assert not deb.data.has_file("/usr/share/doc/nosuchfile", follow_symlinks=False)
            assert not deb.data.has_file("/nosuchdir/nosuchfile", follow_symlinks=True)

            # non-existent files beyond a symlink
            debdatafile = path(self.link_data_dirs[1], "dirlink", "nosuchfile")
            assert not deb.data.has_file(debdatafile, follow_symlinks=False)
            assert not deb.data.has_file(debdatafile, follow_symlinks=True)

    def test_data_get_file(self, sample_deb: str) -> None:
        """ test for round-trip of a data file """
        datafile = self.example_data_files[-1]
        debdatafile = self.example_data_dir / self.example_data_files[-1]

        self._test_file_contents(sample_deb, debdatafile, find_test_file(datafile))

        with pytest.raises(debfile.DebError):
            self._test_file_contents(sample_deb, "/usr/share/doc/nosuchfile", find_test_file(datafile))

        with pytest.raises(debfile.DebError):
            self._test_file_contents(sample_deb, "./usr/share/doc/nosuchfile", find_test_file(datafile))

        with pytest.raises(debfile.DebError):
            self._test_file_contents(sample_deb, "/nosuchdir/nosuchfile", find_test_file(datafile))

        with pytest.raises(debfile.DebError):
            self._test_file_contents(sample_deb, "./nosuchdir/nosuchfile", find_test_file(datafile))

    def test_data_get_file_symlinks(self, sample_deb: str) -> None:
        """ test for traversing symlinks in the package

        links that are within the same directory get automatically resolved
        by tarfile, but links that cross directories do not
        """
        basename = self.example_data_files[0]
        targetdata = find_test_file(basename)
        testlinkfiles = [
            # Format: (path in .deb, fails without symlinks)
            # relative symlink to a file within a directory
            (self.example_data_dir / ("link_" + basename), False),
            # relative symlink to a file
            (Path(self.example_data_dir / self.link_data_dirs[0]) / basename, True),
            # relative symlink to a directory
            (Path(self.example_data_dir / self.link_data_dirs[0]) / "dirlink" / basename, True),
            # absolute symlink to a file
            (Path(self.example_data_dir / self.link_data_dirs[1]) / basename, True),
            # absolute symlink to a directory
            (Path(self.example_data_dir / self.link_data_dirs[1]) / "dirlink" / basename, True),
        ]

        for linkname, fail_without_symlink in testlinkfiles:
            cleanlinkname = os.path.normpath(str(linkname))
            if fail_without_symlink:
                with pytest.raises(debfile.DebError):
                    self._test_file_contents(sample_deb, linkname, targetdata, follow_symlinks=False)
            else:
                self._test_file_contents(sample_deb, linkname, targetdata, follow_symlinks=False)
            self._test_file_contents(sample_deb, cleanlinkname, targetdata, follow_symlinks=True)

    @pytest.mark.skipif(not _dpkg_deb_path, reason="dpkg-deb not installed")
    def test_control(self, sample_deb: str) -> None:
        """ test for control contents equality """
        with os.popen("dpkg-deb -f %s" % sample_deb) as dpkg_deb:
            filecontrol = "".join(dpkg_deb.readlines())

        with debfile.DebFile(sample_deb) as deb:
            for control_file in ["control", "./control"]:
                ctrl = deb.control.get_content(control_file)
                assert ctrl is not None
                assert ctrl.decode("utf-8") == filecontrol
                assert deb.control.get_content("control", encoding="utf-8") == filecontrol

    def test_binnmu_control(self, sample_deb_binnmu: str) -> None:
        """ test for control contents equality """
        with debfile.DebFile(sample_deb_binnmu) as deb:
            ctrl = deb.debcontrol()
            assert ctrl.source == "hellosrc"
            assert ctrl.source_version == "1.2.3"
            assert ctrl['Version'] == "2.10-2"

    def test_md5sums(self, sample_deb: str) -> None:
        """test md5 extraction from .debs"""
        with debfile.DebFile(sample_deb) as deb:
            md5b = deb.md5sums()
            md5 = deb.md5sums(encoding="UTF-8")

            data = [
                (self.example_data_dir / "test_Changes", "73dbb291e900d8cd08e2bb76012a3829"),
            ]
            for f, h in data:
                assert md5b[str(f).encode('UTF-8')] == h
                assert md5[str(f)] == h

    def test_contextmanager(self, sample_deb: str) -> None:
        """test use of DebFile as a contextmanager"""
        with debfile.DebFile(sample_deb) as deb:
            all_files = deb.data.tgz().getnames()
            assert all_files
            assert deb.control.get_content("control")

    def test_open_directly(self, sample_deb: str) -> None:
        """test use of DebFile without the contextmanager"""
        with debfile.DebFile(sample_deb) as deb:
            all_files = deb.data.tgz().getnames()
            assert all_files
            assert deb.control.get_content("control")
