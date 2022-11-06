#!/usr/bin/python
# Copyright (C) 2019 Jelmer Vernooij
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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

"""Tests for debian.watch."""

import pytest

try:
    from StringIO import StringIO  # type: ignore
except ImportError:
    from io import StringIO

try:
    # pylint: disable=unused-import
    from typing import (
        Optional,
        TypeVar,
    )
except ImportError:
    # Missing types aren't important at runtime
    TYPE_CHECKING = False

    # Fake some definitions
    if not TYPE_CHECKING:
        TypeVar = lambda t: None


from debian.watch import (
    expand,
    MissingVersion,
    Watch,
    WatchFile,
    )


class TestParseWatchFile:

    def test_parse_empty(self):
        # type: () -> None
        assert WatchFile.from_lines(StringIO("")) is None

    def test_parse_no_version(self):
        # type: () -> None
        with pytest.raises(MissingVersion):
            WatchFile.from_lines(StringIO("foo\n"))
        with pytest.raises(MissingVersion):
            WatchFile.from_lines(StringIO("foo=bar\n"))

    def test_parse_with_spacing_around_version(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version = 3
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 3
        assert wf.entries == [Watch('https://samba.org/~jelmer/', 'blah-(\\d+).tar.gz')]

    def test_parse_with_script(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
https://samba.org/~jelmer/ blah-(\\d+).tar.gz debian sh blah.sh
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.entries == [
            Watch('https://samba.org/~jelmer/', 'blah-(\\d+).tar.gz', 'debian', 'sh blah.sh')
        ]

    def test_parse_single(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
https://samba.org/~jelmer/blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.entries == [Watch('https://samba.org/~jelmer', 'blah-(\\d+).tar.gz')]

    def test_parse_simple(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.entries == [Watch('https://samba.org/~jelmer/', 'blah-(\\d+).tar.gz')]

    def test_parse_with_opts(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
opts=pgpmode=mangle https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.options == []
        assert wf.entries == [
            Watch('https://samba.org/~jelmer/', 'blah-(\\d+).tar.gz', opts=['pgpmode=mangle'])
        ]

    def test_parse_global_opts(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
opts=pgpmode=mangle
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.options == ['pgpmode=mangle']
        assert wf.entries == [
            Watch('https://samba.org/~jelmer/', 'blah-(\\d+).tar.gz')
        ]

    def test_parse_opt_quotes(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
opts="pgpmode=mangle" https://samba.org/~jelmer blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.entries == [
            Watch('https://samba.org/~jelmer', 'blah-(\\d+).tar.gz', opts=['pgpmode=mangle'])
        ]

    def test_parse_continued_leading_spaces_4(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
opts=pgpmode=mangle,\\
    foo=bar https://samba.org/~jelmer blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.entries == [
            Watch('https://samba.org/~jelmer', 'blah-(\\d+).tar.gz', opts=['pgpmode=mangle', 'foo=bar'])
        ]

    def test_parse_continued_leading_spaces_3(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=3
opts=pgpmode=mangle,\\
    foo=bar blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 3
        assert wf.entries == [
            Watch('foo=bar', 'blah-(\\d+).tar.gz', opts=['pgpmode=mangle', ''])
        ]

    def test_pattern_included(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version=4
https://pypi.debian.net/case/case-(.+).tar.gz debian
"""))
        assert wf is not None
        assert wf.version == 4
        assert wf.entries == [
            Watch('https://pypi.debian.net/case', 'case-(.+).tar.gz', 'debian')
        ]

    def test_parse_weird_quotes(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
# please also check https://pypi.debian.net/case/watch
version=3
opts=repacksuffix=+dfsg",pgpsigurlmangle=s/$/.asc/ \\
https://pypi.debian.net/case/case-(.+)\\.(?:zip|(?:tar\\.(?:gz|bz2|xz))) \\
debian sh debian/repack.stub
"""))
        assert wf is not None
        assert wf.version == 3
        assert wf.entries == [
            Watch(
                'https://pypi.debian.net/case',
                'case-(.+)\\.(?:zip|(?:tar\\.(?:gz|bz2|xz)))',
                'debian', 'sh debian/repack.stub',
                opts=['repacksuffix=+dfsg"', 'pgpsigurlmangle=s/$/.asc/'])
        ]


    def test_package_variable(self):
        # type: () -> None
        wf = WatchFile.from_lines(StringIO("""\
version = 3
https://samba.org/~jelmer/@PACKAGE@ blah-(\\d+).tar.gz
"""))
        assert wf is not None
        assert wf.version == 3
        assert wf.entries == [
            Watch('https://samba.org/~jelmer/@PACKAGE@', 'blah-(\\d+).tar.gz')
        ]

        assert expand(wf.entries[0].url, 'blah') == 'https://samba.org/~jelmer/blah'


class TestDumpWatchFile:

    def test_empty(self):
        # type: () -> None
        wf = WatchFile()
        f = StringIO()
        wf.dump(f)
        assert f.getvalue() == "version=4\n"

    def test_simple(self):
        # type: () -> None
        wf = WatchFile()
        wf.entries = [
            Watch('https://pypi.debian.net/case', 'case-(.+).tar.gz')]
        f = StringIO()
        wf.dump(f)
        assert f.getvalue() == """\
version=4
https://pypi.debian.net/case case-(.+).tar.gz
"""

    def test_opts(self):
        # type: () -> None
        wf = WatchFile()
        wf.entries = [
            Watch('https://samba.org/~jelmer',
                  'blah-(\\d+).tar.gz', opts=['pgpmode=mangle'])]
        wf.options = ['useragent=lynx']
        f = StringIO()
        wf.dump(f)
        assert f.getvalue() == """\
version=4
opts=useragent=lynx
opts=pgpmode=mangle https://samba.org/~jelmer blah-(\\d+).tar.gz
"""

    def test_multiple_lines(self):
        # type: () -> None
        wf = WatchFile()
        wf.entries = [
            Watch('https://samba.org/~jelmer',
                  'blah-(\\d+).tar.gz', opts=['pgpmode=mangle']),
            Watch('https://salsa.debian.org/python-team/blah-(.*).tar.gz')]
        f = StringIO()
        wf.dump(f)
        assert f.getvalue() == """\
version=4
opts=pgpmode=mangle https://samba.org/~jelmer blah-(\\d+).tar.gz
https://salsa.debian.org/python-team/blah-(.*).tar.gz
"""


class TestExpand:

    def test_expand_package(self):
        # type: () -> None
        assert 'foo-1.2.3.tar.gz' == expand('@PACKAGE@-1.2.3.tar.gz', 'foo')

    def test_static(self):
        # type: () -> None
        assert r'foo-[-_]?(\d[\-+\.:\~\da-zA-Z]*)' == expand('foo-@ANY_VERSION@', 'foo')
