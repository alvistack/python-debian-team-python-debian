#!/usr/bin/python
# vim: fileencoding=utf-8
#
# changelog.py -- Python module for Debian changelogs
# Copyright (C) 2006-7 James Westby <jw+debian@jameswestby.net>
# Copyright (C) 2008 Canonical Ltd.
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

# The parsing code is based on that from dpkg which is:
# Copyright 1996 Ian Jackson
# Copyright 2005 Frank Lichtenheld <frank@lichtenheld.de>
# and licensed under the same license as above.

import logging
import os.path

import pytest

from debian import changelog
from debian import debian_support


try:
    # pylint: disable=unused-import
    from typing import (
        Any,
        IO,
        Optional,
        Text,
    )
except ImportError:
    # Missing types aren't important at runtime
    pass


def find_test_file(filename):
    # type: (str) -> str
    """ find a test file that is located within the test suite """
    return os.path.join(os.path.dirname(__file__), filename)


def open_utf8(filename, mode='r'):
    # type: (str, str) -> IO[Text]
    """Open a UTF-8 text file in text mode."""
    return open(filename, mode=mode, encoding='UTF-8')


class TestChangelog:

    def test_create_changelog(self):
        # type: () -> None
        with open(find_test_file('test_changelog')) as f:
            c = f.read()
        cl = changelog.Changelog(c)
        cs = str(cl)
        clines = c.split('\n')
        cslines = cs.split('\n')
        for i in range(len(clines)):
            assert clines[i] == cslines[i]
        assert len(clines) == len(cslines), "Different lengths"

    def test_create_changelog_single_block(self):
        # type: () -> None
        with open(find_test_file('test_changelog')) as f:
            c = f.read()
        cl = changelog.Changelog(c, max_blocks=1)
        cs = str(cl)
        assert cs == \
        """gnutls13 (1:1.4.1-1) unstable; urgency=HIGH

  [ James Westby ]
  * New upstream release. Closes: #123, #456,
    #789. LP: #1234, #2345,
    #3456
  * Remove the following patches as they are now included upstream:
    - 10_certtoolmanpage.diff
    - 15_fixcompilewarning.diff
    - 30_man_hyphen_*.patch
  * Link the API reference in /usr/share/gtk-doc/html as gnutls rather than
    gnutls-api so that devhelp can find it.

 -- Andreas Metzler <ametzler@debian.org>  Sat, 15 Jul 2006 11:11:08 +0200

"""

    def test_modify_changelog(self):
        # type: () -> None
        with open(find_test_file('test_modify_changelog1')) as f:
            c = f.read()
        cl = changelog.Changelog(c)
        cl.package = 'gnutls14'
        cl.version = '1:1.4.1-2'
        cl.distributions = 'experimental'
        cl.urgency = 'medium'
        cl.add_change('  * Add magic foo')
        cl.author = 'James Westby <jw+debian@jameswestby.net>'
        cl.date = 'Sat, 16 Jul 2008 11:11:08 -0200'
        with open(find_test_file('test_modify_changelog2')) as f:
            c = f.read()
        clines = c.split('\n')
        cslines = str(cl).split('\n')
        for i in range(len(clines)):
            assert clines[i] == cslines[i]
        assert len(clines) == len(cslines), "Different lengths"

    def test_preserve_initial_lines(self, caplog):
        # type: (pytest.LogCaptureFixture) -> None
        cl_text = b"""
THIS IS A LINE THAT SHOULD BE PRESERVED BUT IGNORED
haskell-src-exts (1.8.2-3) unstable; urgency=low

  * control: Use versioned Replaces: and Conflicts:

 -- Somebody <nobody@debian.org>  Wed, 05 May 2010 18:01:53 -0300
"""
        with caplog.at_level(logging.WARNING):
            cl = changelog.Changelog(cl_text)
        assert caplog.record_tuples == [(
            "debian.changelog",
            logging.WARNING,
            'Unexpected line while looking for first heading: '
            'THIS IS A LINE THAT SHOULD BE PRESERVED BUT IGNORED'
        )]

        assert cl_text == bytes(cl)

    def test_add_changelog_section(self):
        # type: () -> None
        with open(find_test_file('test_modify_changelog2')) as f:
            c = f.read()
        cl = changelog.Changelog(c)
        cl.new_block(package='gnutls14',
                version=debian_support.Version('1:1.4.1-3'),
                distributions='experimental',
                urgency='low',
                author='James Westby <jw+debian@jameswestby.net>')

        with pytest.raises(changelog.ChangelogCreateError):
            cl.__str__()

        cl.set_date('Sat, 16 Jul 2008 11:11:08 +0200')
        cl.add_change('')
        cl.add_change('  * Foo did not work, let us try bar')
        cl.add_change('')

        f = open(find_test_file('test_modify_changelog3'))
        c = f.read()
        f.close()
        clines = c.split('\n')
        cslines = str(cl).split('\n')
        for i in range(len(clines)):
            assert clines[i] == cslines[i]
        assert len(clines) == len(cslines), "Different lengths"

    def test_strange_changelogs(self):
        # type: () -> None
        """ Just opens and parses a strange changelog """
        with open(find_test_file('test_strange_changelog')) as f:
            c = f.read()
        cl = changelog.Changelog(c)

    def test_set_version_with_string(self):
        # type: () -> None
        with open(find_test_file('test_modify_changelog1')) as f:
            c1 = changelog.Changelog(f.read())
            f.seek(0)
            c2 = changelog.Changelog(f.read())
        c1.version = '1:2.3.5-2'
        c2.version = debian_support.Version('1:2.3.5-2')
        assert c1.version == c2.version
        assert c1.full_version == c2.full_version
        assert c1.epoch == c2.epoch
        assert c1.upstream_version == c2.upstream_version
        assert c1.debian_version == c2.debian_version

    def test_changelog_no_author(self):
        # type: () -> None
        cl_no_author = """gnutls13 (1:1.4.1-1) unstable; urgency=low

  * New upstream release.

 --
"""
        c1 = changelog.Changelog()
        c1.parse_changelog(cl_no_author, allow_empty_author=True)
        assert c1.author == None
        assert c1.date == None
        assert c1.package == "gnutls13"
        with pytest.raises(changelog.ChangelogCreateError):
            str(c1)
        assert c1._format(allow_missing_author=True) == cl_no_author
        c2 = changelog.Changelog()
        with pytest.raises(changelog.ChangelogParseError):
            c2.parse_changelog(cl_no_author)

    def test_magic_version_properties(self):
        # type: () -> None
        with open(find_test_file('test_changelog')) as f:
            c = changelog.Changelog(f)
        assert c.debian_version == '1'
        assert c.full_version == '1:1.4.1-1'
        assert c.upstream_version == '1.4.1'
        assert c.epoch == '1'
        assert str(c.version) == c.full_version

    def test_bugs_closed(self):
        # type: () -> None
        with open(find_test_file('test_changelog')) as f:
            c = iter(changelog.Changelog(f))
        # test bugs in a list
        block = next(c)
        assert block.bugs_closed == [123, 456, 789]
        assert block.lp_bugs_closed == [1234, 2345, 3456]
        # test bugs in parentheses
        block = next(c)
        assert block.bugs_closed == [375815]
        assert block.lp_bugs_closed == []

    def test_allow_full_stops_in_distribution(self):
        # type: () -> None
        with open(find_test_file('test_changelog_full_stops')) as f:
            c = changelog.Changelog(f)
        assert c.debian_version == None
        assert c.full_version == '1.2.3'
        assert str(c.version) == c.full_version

    def test_str_consistent(self):
        # type: () -> None
        # The parsing of the changelog (including the string representation)
        # should be consistent whether we give a single string, a list of
        # lines, or a file object to the Changelog initializer
        with open(find_test_file('test_changelog')) as f:
            cl_data = f.read()
            f.seek(0)
            c1 = changelog.Changelog(f)
        c2 = changelog.Changelog(cl_data)
        c3 = changelog.Changelog(cl_data.splitlines())
        for c in (c1, c2, c3):
            assert str(c) == cl_data

    def test_utf8_encoded_file_input(self):
        # type: () -> None
        f = open_utf8(find_test_file('test_changelog_unicode'))
        c = changelog.Changelog(f)
        f.close()
        u = str(c)
        expected_u = """haskell-src-exts (1.8.2-3) unstable; urgency=low

  * control: Use versioned Replaces: and Conflicts:

 -- Marco T\xfalio Gontijo e Silva <marcot@debian.org>  Wed, 05 May 2010 18:01:53 -0300

haskell-src-exts (1.8.2-2) unstable; urgency=low

  * debian/control: Rename -doc package.

 -- Marco T\xfalio Gontijo e Silva <marcot@debian.org>  Tue, 16 Mar 2010 10:59:48 -0300
"""
        assert u == expected_u
        assert bytes(c) == u.encode('utf-8')

    def test_unicode_object_input(self):
        # type: () -> None
        with open(find_test_file('test_changelog_unicode'), 'rb') as f:
            c_bytes = f.read()
        c_unicode = c_bytes.decode('utf-8')
        c = changelog.Changelog(c_unicode)
        assert str(c) == c_unicode
        assert bytes(c) == c_bytes

    def test_non_utf8_encoding(self):
        # type: () -> None
        with open(find_test_file('test_changelog_unicode'), 'rb') as f:
            c_bytes = f.read()
        c_unicode = c_bytes.decode('utf-8')
        c_latin1_str = c_unicode.encode('latin1')
        c = changelog.Changelog(c_latin1_str, encoding='latin1')
        assert str(c) == c_unicode
        assert bytes(c) == c_latin1_str
        for block in c:
            assert bytes(block) == str(block).encode('latin1')

    def test_malformed_date(self, caplog):
        # type: (pytest.LogCaptureFixture) -> None
        c_text = """package (1.0-1) codename; urgency=medium

  * minimal example reproducer of malformed date line

 -- John Smith <john.smith@example.com> Tue, 27 Sep 2016 14:08:04 -0600
 """
        # In strict mode, exceptions should be raised by the malformed entry
        with pytest.raises(changelog.ChangelogParseError):
            c = changelog.Changelog(c_text, strict=True)
        # In non-strict mode, warnings should be emitted by the malformed entry
        with caplog.at_level(logging.WARNING):
            c = changelog.Changelog(c_text, strict=False)
        assert len(c) == 1
        assert caplog.record_tuples == [(
            "debian.changelog",
            logging.WARNING,
            'Badly formatted trailer line:  '
            '-- John Smith <john.smith@example.com> '
            'Tue, 27 Sep 2016 14:08:04 -0600'
        )]

    def test_block_iterator(self):
        # type: () -> None
        with open(find_test_file('test_changelog')) as f:
            c = changelog.Changelog(f)
        assert [str(b) for b in c._blocks] == [str(b) for b in c]

    def test_block_access(self):
        # type: () -> None
        """ test random access to changelog entries """
        with open(find_test_file('test_changelog')) as f:
            c = changelog.Changelog(f)
        assert str(c[2].version) == '1.4.0-2', \
                         'access by sequence number'
        assert str(c['1.4.0-1'].version) == '1.4.0-1', \
                         'access by version string'
        assert str(c[debian_support.Version('1.3.5-1.1')].version) == \
                         '1.3.5-1.1', \
                         'access by Version object'

    def test_len(self):
        # type: () -> None
        with open(find_test_file('test_changelog')) as f:
            c = changelog.Changelog(f)
        assert len(c._blocks) == len(c)
