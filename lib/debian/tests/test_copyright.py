#! /usr/bin/python
## vim: fileencoding=utf-8

# Copyright (C) 2014 Google, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import logging
import re

import pytest

from debian import copyright
from debian import deb822
from debian._deb822_repro import parse_deb822_file, Deb822ParagraphElement


try:
    # pylint: disable=unused-import
    from typing import (
        Any,
        Generator,
        List,
        Pattern,
        Sequence,
        Text,
        no_type_check,
        TYPE_CHECKING,
    )
except ImportError:
    # Lack of typing is not important at runtime
    TYPE_CHECKING = False


SIMPLE = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: X Solitaire
Source: ftp://ftp.example.com/pub/games
Files-Excluded:
  non-free-file.txt
  *.exe
Files-Included:
  foo.exe

Files: *
Copyright: Copyright 1998 John Doe <jdoe@example.com>
License: GPL-2+
 This program is free software; you can redistribute it
 and/or modify it under the terms of the GNU General Public
 License as published by the Free Software Foundation; either
 version 2 of the License, or (at your option) any later
 version.
 .
 This program is distributed in the hope that it will be
 useful, but WITHOUT ANY WARRANTY; without even the implied
 warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
 PURPOSE.  See the GNU General Public License for more
 details.
 .
 You should have received a copy of the GNU General Public
 License along with this package; if not, write to the Free
 Software Foundation, Inc., 51 Franklin St, Fifth Floor,
 Boston, MA  02110-1301 USA
 .
 On Debian systems, the full text of the GNU General Public
 License version 2 can be found in the file
 `/usr/share/common-licenses/GPL-2'.

Files: debian/*
Copyright: Copyright 1998 Jane Smith <jsmith@example.net>
License: GPL-2+
 [LICENSE TEXT]
"""

GPL_TWO_PLUS_TEXT = """\
This program is free software; you can redistribute it
and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation; either
version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be
useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE.  See the GNU General Public License for more
details.

You should have received a copy of the GNU General Public
License along with this package; if not, write to the Free
Software Foundation, Inc., 51 Franklin St, Fifth Floor,
Boston, MA  02110-1301 USA

On Debian systems, the full text of the GNU General Public
License version 2 can be found in the file
`/usr/share/common-licenses/GPL-2'."""

MULTI_LICENSE = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Project Y

Files: *
Copyright: Copyright 2000 Company A
License: ABC

Files: src/baz.*
Copyright: Copyright 2000 Company A
           Copyright 2001 Company B
License: ABC

Files: debian/*
Copyright: Copyright 2003 Debian Developer <someone@debian.org>
License: 123

Files: debian/rules
Copyright: Copyright 2003 Debian Developer <someone@debian.org>
           Copyright 2004 Someone Else <foo@bar.com>
License: 123

License: ABC
 [ABC TEXT]

License: 123
 [123 TEXT]
"""

DUPLICATE_FIELD = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: X Solitaire

Files: *
Copyright: Copyright 1998 John Doe <johndoe@example.com>
Copyright: Copyright 1999 Jane Doe <janedoe@example.com>
License: GPL-2+
 This program is free software; you can redistribute it
 and/or modify it under the terms of the GNU General Public
 License as published by the Free Software Foundation; either
 version 2 of the License, or (at your option) any later
 version.
 .
 This program is distributed in the hope that it will be
 useful, but WITHOUT ANY WARRANTY; without even the implied
 warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
 PURPOSE.  See the GNU General Public License for more
 details.
 .
 You should have received a copy of the GNU General Public
 License along with this package; if not, write to the Free
 Software Foundation, Inc., 51 Franklin St, Fifth Floor,
 Boston, MA  02110-1301 USA
 .
 On Debian systems, the full text of the GNU General Public
 License version 2 can be found in the file
 `/usr/share/common-licenses/GPL-2'.
"""


NOT_MACHINE_READABLE = """\
This is the Debian GNU prepackaged version of the FSF's GNU hello

Originally packaged by Joe Example <joe@example.com>
"""


FORMAT = 'https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/'


class TestRestrictedWrapper:
    class Wrapper(copyright._RestrictedWrapper):
        restricted_field = deb822.RestrictedField('Restricted-Field')
        required_field = deb822.RestrictedField('Required-Field', allow_none=False)
        space_separated = deb822.RestrictedField(
                'Space-Separated',
                from_str=lambda s: tuple((s or '').split()),
                to_str=lambda seq: ' '.join(_no_space(s) for s in seq) or None)

    def test_unrestricted_get_and_set(self):
        # type: () -> None
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Foo'] = 'bar'

        wrapper = self.Wrapper(data)
        assert 'bar' == wrapper['Foo']
        wrapper['foo'] = 'baz'
        assert 'baz' == wrapper['Foo']
        assert 'baz' == wrapper['foo']

        multiline = 'First line\n Another line'
        wrapper['X-Foo-Bar'] = multiline
        assert multiline == wrapper['X-Foo-Bar']
        assert multiline == wrapper['x-foo-bar']

        expected_data = Deb822ParagraphElement.new_empty_paragraph()
        expected_data['Foo'] = 'baz'
        expected_data['X-Foo-Bar'] = multiline
        assert expected_data.keys() == data.keys()
        assert expected_data == data

    @no_type_check
    def test_trivially_restricted_get_and_set(self):
        # mypy can't cope with the metaprogramming here
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Required-Field'] = 'some value'

        wrapper = self.Wrapper(data)
        assert 'some value' == wrapper.required_field
        assert 'some value' == wrapper['Required-Field']
        assert 'some value' == wrapper['required-field']
        assert wrapper.restricted_field is None

        with pytest.raises(deb822.RestrictedFieldError):
            wrapper['Required-Field'] = 'foo'
        with pytest.raises(deb822.RestrictedFieldError):
            wrapper['required-field'] = 'foo'
        with pytest.raises(deb822.RestrictedFieldError):
            wrapper['Restricted-Field'] = 'foo'
        with pytest.raises(deb822.RestrictedFieldError):
            wrapper['Restricted-field'] = 'foo'

        with pytest.raises(deb822.RestrictedFieldError):
            del wrapper['Required-Field']
        with pytest.raises(deb822.RestrictedFieldError):
            del wrapper['required-field']
        with pytest.raises(deb822.RestrictedFieldError):
            del wrapper['Restricted-Field']
        with pytest.raises(deb822.RestrictedFieldError):
            del wrapper['restricted-field']

        with pytest.raises(TypeError):
            wrapper.required_field = None

        wrapper.restricted_field = 'special value'
        assert 'special value' == data['Restricted-Field']
        wrapper.restricted_field = None
        assert not ('Restricted-Field' in data)
        assert wrapper.restricted_field is None

        wrapper.required_field = 'another value'
        assert 'another value' == data['Required-Field']

    @no_type_check
    def test_set_already_none_to_none(self):
        # mypy can't cope with the metaprogramming here
        data = Deb822ParagraphElement.new_empty_paragraph()
        wrapper = self.Wrapper(data)
        wrapper.restricted_field = 'Foo'
        wrapper.restricted_field = None
        assert not ('restricted-field' in data)
        wrapper.restricted_field = None
        assert not ('restricted-field' in data)

    @no_type_check
    def test_processed_get_and_set(self):
        # mypy can't cope with the metaprogramming here
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Space-Separated'] = 'foo bar baz'

        wrapper = self.Wrapper(data)
        assert ('foo', 'bar', 'baz') == wrapper.space_separated
        wrapper.space_separated = ['bar', 'baz', 'quux']
        assert 'bar baz quux' == data['space-separated']
        assert 'bar baz quux' == wrapper['space-separated']
        assert ('bar', 'baz', 'quux') == wrapper.space_separated

        with pytest.raises(ValueError, match="whitespace not allowed"):
            wrapper.space_separated = ('foo', 'bar baz')

        wrapper.space_separated = None
        assert () == wrapper.space_separated
        assert not ('space-separated' in data)
        assert not ('Space-Separated' in data)

        wrapper.space_separated = ()
        assert () == wrapper.space_separated
        assert not ('space-separated' in data)
        assert not ('Space-Separated' in data)

    def test_dump(self):   # type: ignore
        # mypy can't cope with the metaprogramming here
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Foo'] = 'bar'
        data['Baz'] = 'baz'
        data['Space-Separated'] = 'baz quux'
        data['Required-Field'] = 'required value'
        data['Restricted-Field'] = 'restricted value'

        wrapper = self.Wrapper(data)
        assert data.dump() == wrapper.dump()

        wrapper.restricted_field = 'another value'        # type: ignore
        wrapper.space_separated = ('bar', 'baz', 'quux')  # type: ignore
        assert data.dump() == wrapper.dump()


class TestLineBased:
    """Test for _LineBased.{to,from}_str"""

    # Alias for less typing.
    lb = copyright._LineBased

    def test_from_str_none(self):
        # type: () -> None
        assert () == self.lb.from_str(None)

    def test_from_str_empty(self):
        # type: () -> None
        assert () == self.lb.from_str('')

    def test_from_str_single_line(self):
        # type: () -> None
        assert ('Foo Bar <foo@bar.com>',) == \
            self.lb.from_str('Foo Bar <foo@bar.com>')

    def test_from_str_single_value_after_newline(self):
        # type: () -> None
        assert ('Foo Bar <foo@bar.com>',) == \
            self.lb.from_str('\n Foo Bar <foo@bar.com>')

    def test_from_str_multiline(self):
        # type: () -> None
        assert ('Foo Bar <foo@bar.com>', 'http://bar.com/foo') == \
            self.lb.from_str('\n Foo Bar <foo@bar.com>\n http://bar.com/foo')

    def test_to_str_empty(self):
        # type: () -> None
        assert self.lb.to_str([]) is None
        assert self.lb.to_str(()) is None

    def test_to_str_single(self):
        # type: () -> None
        assert 'Foo Bar <foo@bar.com>' == \
            self.lb.to_str(['Foo Bar <foo@bar.com>'])

    def test_to_str_multi_list(self):
        # type: () -> None
        assert '\n Foo Bar <foo@bar.com>\n http://bar.com/foo' == \
            self.lb.to_str(
                ['Foo Bar <foo@bar.com>', 'http://bar.com/foo'])

    def test_to_str_multi_tuple(self):
        # type: () -> None
        assert '\n Foo Bar <foo@bar.com>\n http://bar.com/foo' == \
            self.lb.to_str(
                ('Foo Bar <foo@bar.com>', 'http://bar.com/foo'))

    def test_to_str_empty_value(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not be empty'):
            self.lb.to_str(['foo', '', 'bar'])

    def test_to_str_whitespace_only_value(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not be empty'):
            self.lb.to_str(['foo', ' \t', 'bar'])

    def test_to_str_elements_stripped(self):
        # type: () -> None
        assert '\n Foo Bar <foo@bar.com>\n http://bar.com/foo' == \
            self.lb.to_str(
                (' Foo Bar <foo@bar.com>\t', ' http://bar.com/foo  '))

    def test_to_str_newlines_single(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not contain newlines'):
            self.lb.to_str([' Foo Bar <foo@bar.com>\n http://bar.com/foo  '])

    def test_to_str_newlines_multi(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not contain newlines'):
            self.lb.to_str(
                ['bar', ' Foo Bar <foo@bar.com>\n http://bar.com/foo  '])


class TestSpaceSeparated:
    """Tests for _SpaceSeparated.{to,from}_str."""

    # Alias for less typing.
    ss = copyright._SpaceSeparated

    def test_from_str_none(self):
        # type: () -> None
        assert () == self.ss.from_str(None)

    def test_from_str_empty(self):
        # type: () -> None
        assert () == self.ss.from_str(' ')
        assert () == self.ss.from_str('')

    def test_from_str_single(self):
        # type: () -> None
        assert ('foo',) == self.ss.from_str('foo')
        assert ('bar',) == self.ss.from_str(' bar ')

    def test_from_str_multi(self):
        # type: () -> None
        assert ('foo', 'bar', 'baz') == self.ss.from_str('foo bar baz')
        assert ('bar', 'baz', 'quux') == self.ss.from_str(' bar baz quux \t ')

    def test_to_str_empty(self):
        # type: () -> None
        assert self.ss.to_str([]) is None
        assert self.ss.to_str(()) is None

    def test_to_str_single(self):
        # type: () -> None
        assert 'foo' == self.ss.to_str(['foo'])

    def test_to_str_multi(self):
        # type: () -> None
        assert 'foo bar baz' == self.ss.to_str(['foo', 'bar', 'baz'])

    def test_to_str_empty_value(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not be empty'):
            self.ss.to_str(['foo', '', 'bar'])

    def test_to_str_value_has_space_single(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not contain whitespace'):
            self.ss.to_str([' baz quux '])

    def test_to_str_value_has_space_multi(self):
        # type: () -> None
        with pytest.raises(ValueError, match='values must not contain whitespace'):
            self.ss.to_str(['foo', ' baz quux '])


class TestCopyright:

    @no_type_check
    def test_basic_parse_success(self):
        # type: () -> None
        c = copyright.Copyright(sequence=SIMPLE.splitlines(True))
        assert FORMAT == c.header.format
        assert FORMAT == c.header['Format']
        assert 'X Solitaire' == c.header.upstream_name
        assert 'X Solitaire' == c.header['Upstream-Name']
        assert 'ftp://ftp.example.com/pub/games' == c.header.source
        assert 'ftp://ftp.example.com/pub/games' == c.header['Source']
        assert ('non-free-file.txt', '*.exe') == c.header.files_excluded
        assert ('foo.exe', ) == c.header.files_included
        assert c.header.license is None

    def test_parse_and_dump(self):
        # type: () -> None
        c = copyright.Copyright(sequence=SIMPLE.splitlines(True))
        dumped = c.dump()
        assert SIMPLE == dumped

    def test_duplicate_field(self):
        # type: () -> None
        c = copyright.Copyright(
            sequence=DUPLICATE_FIELD.splitlines(True), strict=False)
        dumped = c.dump()
        assert DUPLICATE_FIELD == dumped
        with pytest.raises(ValueError):
            copyright.Copyright(sequence=DUPLICATE_FIELD.splitlines(True), strict=True)

    def test_all_paragraphs(self):
        # type: () -> None
        c = copyright.Copyright(MULTI_LICENSE.splitlines(True))
        expected = []  # type: List[copyright.AllParagraphTypes]
        expected.append(c.header)
        expected.extend(list(c.all_files_paragraphs()))
        expected.extend(list(c.all_license_paragraphs()))
        assert expected == list(c.all_paragraphs())
        assert expected == list(c)

    @no_type_check
    def test_all_files_paragraphs(self):
        # type: () -> None
        c = copyright.Copyright(sequence=SIMPLE.splitlines(True))
        assert [('*',), ('debian/*',)] == \
            [fp.files for fp in c.all_files_paragraphs()]

        c = copyright.Copyright()
        assert [] == list(c.all_files_paragraphs())

    def test_find_files_paragraph(self):
        # type: () -> None
        c = copyright.Copyright(sequence=SIMPLE.splitlines(True))
        paragraphs = list(c.all_files_paragraphs())

        assert paragraphs[0] is c.find_files_paragraph('Makefile')
        assert paragraphs[0] is c.find_files_paragraph('src/foo.cc')
        assert paragraphs[1] is c.find_files_paragraph('debian/rules')
        assert paragraphs[1] is c.find_files_paragraph('debian/a/b.py')

    def test_find_files_paragraph_some_unmatched(self):
        # type: () -> None
        c = copyright.Copyright()
        files1 = copyright.FilesParagraph.create(
            ['foo/*'], 'CompanyA', copyright.License('ISC'))
        files2 = copyright.FilesParagraph.create(
            ['bar/*'], 'CompanyB', copyright.License('Apache'))
        c.add_files_paragraph(files1)
        c.add_files_paragraph(files2)
        paragraphs = list(c.all_files_paragraphs())
        assert paragraphs[0] is c.find_files_paragraph('foo/bar.cc')
        assert paragraphs[1] is c.find_files_paragraph('bar/baz.cc')
        assert c.find_files_paragraph('baz/quux.cc') is None
        assert c.find_files_paragraph('Makefile') is None

        assert """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/

Files: foo/*
Copyright: CompanyA
License: ISC

Files: bar/*
Copyright: CompanyB
License: Apache
""" == c.dump()

    @no_type_check
    def test_all_license_paragraphs(self):
        # type: () -> None
        c = copyright.Copyright(sequence=SIMPLE.splitlines(True))
        assert [] == list(c.all_license_paragraphs())

        c = copyright.Copyright(MULTI_LICENSE.splitlines(True))
        assert [copyright.License('ABC', '[ABC TEXT]'),
             copyright.License('123', '[123 TEXT]')] == \
            list(p.license for p in c.all_license_paragraphs())

        c.add_license_paragraph(copyright.LicenseParagraph.create(
            copyright.License('Foo', '[FOO TEXT]')))
        assert [copyright.License('ABC', '[ABC TEXT]'),
             copyright.License('123', '[123 TEXT]'),
             copyright.License('Foo', '[FOO TEXT]')] == \
            list(p.license for p in c.all_license_paragraphs())

    def test_error_on_invalid(self):
        # type: () -> None
        lic = SIMPLE.splitlines(True)
        with pytest.raises(copyright.MachineReadableFormatError) as cm:
            # missing License field from 1st Files stanza
            c = copyright.Copyright(sequence=lic[0:10])

        with pytest.raises(copyright.MachineReadableFormatError) as cm:
            # missing Files field from 1st Files stanza
            c = copyright.Copyright(sequence=(lic[0:9] + lic[10:11]))

        with pytest.raises(copyright.MachineReadableFormatError) as cm:
            # missing Copyright field from 1st Files stanza
            c = copyright.Copyright(sequence=(lic[0:10] + lic[11:11]))

    def test_not_machine_readable(self):
        # type: () -> None
        with pytest.raises(copyright.NotMachineReadableError):
            copyright.Copyright(sequence=NOT_MACHINE_READABLE.splitlines(True))


class TestMultline:
    """Test cases for format_multiline{,_lines} and parse_multline{,_as_lines}.
    """

    @pytest.fixture(autouse=True)
    def data(self):
        # type: () -> Generator[None, None, None]
        paragraphs = list(parse_deb822_file(SIMPLE.splitlines(True)))
        self.formatted = paragraphs[1]['License']
        self.parsed = 'GPL-2+\n' + GPL_TWO_PLUS_TEXT
        self.parsed_lines = self.parsed.splitlines()
        yield

    def test_format_multiline(self, data):
        # type: (None) -> None
        assert None == copyright.format_multiline(None)
        assert 'Foo' == copyright.format_multiline('Foo')
        assert 'Foo\n Bar baz\n .\n Quux.' == \
            copyright.format_multiline('Foo\nBar baz\n\nQuux.')
        assert self.formatted == copyright.format_multiline(self.parsed)

    def test_parse_multiline(self, data):
        # type: (None) -> None
        assert None == copyright.parse_multiline(None)
        assert 'Foo' == copyright.parse_multiline('Foo')
        assert 'Foo\nBar baz\n\nQuux.' == \
            copyright.parse_multiline('Foo\n Bar baz\n .\n Quux.')
        assert self.parsed == copyright.parse_multiline(self.formatted)

    def test_format_multiline_lines(self, data):
        # type: (None) -> None
        assert '' == copyright.format_multiline_lines([])
        assert 'Foo' == copyright.format_multiline_lines(['Foo'])
        assert 'Foo\n Bar baz\n .\n Quux.' == \
            copyright.format_multiline_lines(
                ['Foo', 'Bar baz', '', 'Quux.'])
        assert self.formatted == \
            copyright.format_multiline_lines(self.parsed_lines)

    def test_parse_multiline_as_lines(self, data):
        # type: (None) -> None
        assert [] == copyright.parse_multiline_as_lines('')
        assert ['Foo'] == copyright.parse_multiline_as_lines('Foo')
        assert ['Foo', 'Bar baz', '', 'Quux.'] == \
            copyright.parse_multiline_as_lines(
                'Foo\n Bar baz\n .\n Quux.')
        assert self.parsed_lines == \
            copyright.parse_multiline_as_lines(self.formatted)

    def test_parse_format_inverses(self, data):
        # type: (None) -> None
        assert self.formatted == \
            copyright.format_multiline(
                copyright.parse_multiline(self.formatted))

        assert self.formatted == \
            copyright.format_multiline_lines(
                copyright.parse_multiline_as_lines(self.formatted))

        assert self.parsed == \
            copyright.parse_multiline(
                copyright.format_multiline(self.parsed))

        assert self.parsed_lines == \
            copyright.parse_multiline_as_lines(
                copyright.format_multiline_lines(self.parsed_lines))


class TestLicense:

    def test_empty_text(self):
        # type: () -> None
        l = copyright.License('GPL-2+')
        assert 'GPL-2+' == l.synopsis
        assert '' == l.text
        assert 'GPL-2+' == l.to_str()

    def test_newline_in_synopsis(self):
        # type: () -> None
        with pytest.raises(ValueError, match='must be single line'):
            copyright.License('foo\n bar')

    def test_nonempty_text(self):
        # type: () -> None
        text = (
            'Foo bar.\n'
            '\n'
            'Baz.\n'
            'Quux\n'
            '\n'
            'Bang and such.')
        l = copyright.License('GPL-2+', text=text)
        assert text == l.text
        assert ('GPL-2+\n'
             ' Foo bar.\n'
             ' .\n'
             ' Baz.\n'
             ' Quux\n'
             ' .\n'
             ' Bang and such.') == \
            l.to_str()

    def test_typical(self):
        # type: () -> None
        paragraphs = list(parse_deb822_file(SIMPLE.splitlines(True)))
        p = paragraphs[1]
        l = copyright.License.from_str(p['license'])
        if l is not None:
            # CRUFT: conditional only needed for mypy
            #
            assert 'GPL-2+' == l.synopsis
            assert GPL_TWO_PLUS_TEXT == l.text
            assert p['license'] == l.to_str()
        else:
            assert l is not None


class TestLicenseParagraphTest:

    @no_type_check
    def test_properties(self):
        # type: () -> None
        d = Deb822ParagraphElement.new_empty_paragraph()
        d['License'] = 'GPL-2'
        lp = copyright.LicenseParagraph(d)
        assert 'GPL-2' == lp['License']
        assert copyright.License('GPL-2') == lp.license
        assert lp.comment is None
        lp.comment = "Some comment."
        assert "Some comment." == lp.comment
        assert "Some comment." == lp['comment']

        lp.license = copyright.License('GPL-2+', '[LICENSE TEXT]')
        assert copyright.License('GPL-2+', '[LICENSE TEXT]') == lp.license
        assert 'GPL-2+\n [LICENSE TEXT]' == lp['license']

        with pytest.raises(TypeError, match='value must not be None'):
            lp.license = None

    def test_no_license(self):
        # type: () -> None
        d = Deb822ParagraphElement.new_empty_paragraph()
        with pytest.raises(ValueError, match='"License" field required'):
            copyright.LicenseParagraph(d)

    def test_also_has_files(self):
        # type: () -> None
        d = Deb822ParagraphElement.new_empty_paragraph()
        d['License'] = 'GPL-2\n [LICENSE TEXT]'
        d['Files'] = '*'
        with pytest.raises(ValueError, match='input appears to be a Files paragraph'):
            copyright.LicenseParagraph(d)

    def test_try_set_files(self):
        # type: () -> None

        d = Deb822ParagraphElement.new_empty_paragraph()
        d['License'] = 'GPL-2\n [LICENSE TEXT]'
        lp = copyright.LicenseParagraph(d)
        with pytest.raises(deb822.RestrictedFieldError):
            lp['Files'] = 'foo/*'


class TestGlobsToRe:

    flags = re.MULTILINE | re.DOTALL

    def assertReEqual(self, a, b):
        # type: (Pattern[Text], Pattern[Text]) -> None
        assert a.pattern == b.pattern
        assert a.flags == b.flags

    def test_empty(self):
        # type: () -> None
        self.assertReEqual(
            re.compile(r'\Z', self.flags), copyright.globs_to_re([]))

    def test_star(self):
        # type: () -> None
        pat = copyright.globs_to_re(['*'])
        self.assertReEqual(re.compile(r'.*\Z', self.flags), pat)
        assert pat.match('foo')
        assert pat.match('foo/bar/baz')

    def test_star_prefix(self):
        # type: () -> None
        e = re.escape
        pat = copyright.globs_to_re(['*.in'])
        expected = re.compile('.*' + e('.in') + r'\Z', self.flags)
        self.assertReEqual(expected, pat)
        assert not pat.match('foo')
        assert not pat.match('in')
        assert pat.match('Makefile.in')
        assert not pat.match('foo/bar/in')
        assert pat.match('foo/bar/Makefile.in')

    def test_star_prefix_with_slash(self):
        # type: () -> None
        e = re.escape
        pat = copyright.globs_to_re(['*/Makefile.in'])
        expected = re.compile('.*' + e('/Makefile.in') + r'\Z', self.flags)
        self.assertReEqual(expected, pat)
        assert not pat.match('foo')
        assert not pat.match('in')
        assert not pat.match('foo/bar/in')
        assert pat.match('foo/Makefile.in')
        assert pat.match('foo/bar/Makefile.in')

    def test_question_mark(self):
        # type: () -> None
        e = re.escape
        pat = copyright.globs_to_re(['foo/messages.??_??.txt'])
        expected = re.compile(
            e('foo/messages.') + '..' + e('_') + '..' + e('.txt') + r'\Z',
            self.flags)
        self.assertReEqual(expected, pat)
        assert not pat.match('messages.en_US.txt')
        assert pat.match('foo/messages.en_US.txt')
        assert pat.match('foo/messages.ja_JP.txt')
        assert not pat.match('foo/messages_ja_JP.txt')

    def test_multi_literal(self):
        # type: () -> None
        e = re.escape
        pat = copyright.globs_to_re(['Makefile.in', 'foo/bar'])
        expected = re.compile(
            e('Makefile.in') + '|' + e('foo/bar') + r'\Z', self.flags)
        self.assertReEqual(expected, pat)
        assert pat.match('Makefile.in')
        assert not pat.match('foo/Makefile.in')
        assert pat.match('foo/bar')
        assert not pat.match('foo/barbaz')
        assert not pat.match('foo/bar/baz')
        assert not pat.match('a/foo/bar')

    def test_multi_wildcard(self):
        # type: () -> None
        e = re.escape
        pat = copyright.globs_to_re(
            ['debian/*', '*.Debian', 'translations/fr_??/*'])
        expected = re.compile(
            e('debian/') + '.*|.*' + e('.Debian') + '|' +
            e('translations/fr_') + '..' + e('/') + r'.*\Z',
            self.flags)
        self.assertReEqual(expected, pat)
        assert pat.match('debian/rules')
        assert not pat.match('other/debian/rules')
        assert pat.match('README.Debian')
        assert pat.match('foo/bar/README.Debian')
        assert pat.match('translations/fr_FR/a.txt')
        assert pat.match('translations/fr_BE/a.txt')
        assert not pat.match('translations/en_US/a.txt')

    def test_literal_backslash(self):
        # type: () -> None
        e = re.escape
        pat = copyright.globs_to_re([r'foo/bar\\baz.c', r'bar/quux\\'])
        expected = re.compile(
            e(r'foo/bar\baz.c') + '|' + e('bar/quux\\') + r'\Z', self.flags)
        self.assertReEqual(expected, pat)

        assert not pat.match('foo/bar.baz.c')
        assert not pat.match('foo/bar/baz.c')
        assert pat.match(r'foo/bar\baz.c')
        assert not pat.match('bar/quux')
        assert pat.match('bar/quux\\')

    @no_type_check
    def test_illegal_backslash(self):
        # type: () -> None
        with pytest.raises(ValueError) as cm:
            copyright.globs_to_re([r'foo/a\b.c'])
            assert (r'invalid escape sequence: \b',) == \
                             cm.exception.args

        with pytest.raises(ValueError) as cm:
            copyright.globs_to_re('foo/bar\\')
            assert ('single backslash not allowed at end',) == \
                             cm.exception.args


class TestFilesParagraph:

    @pytest.fixture(autouse=True)
    def data(self):
        # type: () -> Generator[None, None, None]
        self.prototype = Deb822ParagraphElement.new_empty_paragraph()
        self.prototype['Files'] = '*'
        self.prototype['Copyright'] = 'Foo'
        self.prototype['License'] = 'ISC'
        yield

    @no_type_check
    def test_files_property(self, data):
        # type: (None) -> None
        fp = copyright.FilesParagraph(self.prototype)
        assert ('*',) == fp.files

        fp.files = ['debian/*']
        assert ('debian/*',) == fp.files
        assert 'debian/*' == fp['files']

        fp.files = ['src/foo/*', 'src/bar/*']
        assert ('src/foo/*', 'src/bar/*') == fp.files
        assert 'src/foo/* src/bar/*' == fp['files']

        with pytest.raises(TypeError):
            fp.files = None

        self.prototype['Files'] = 'foo/*\tbar/*\n\tbaz/*\n quux/*'
        fp = copyright.FilesParagraph(self.prototype)
        assert ('foo/*', 'bar/*', 'baz/*', 'quux/*') == fp.files

    @no_type_check
    def test_license_property(self, data):
        # type: (None) -> None
        fp = copyright.FilesParagraph(self.prototype)
        assert copyright.License('ISC') == fp.license
        fp.license = copyright.License('ISC', '[LICENSE TEXT]')
        assert copyright.License('ISC', '[LICENSE TEXT]') == fp.license
        assert 'ISC\n [LICENSE TEXT]' == fp['license']

        with pytest.raises(TypeError):
            fp.license = None

    def test_matches(self, data):
        # type: (None) -> None
        fp = copyright.FilesParagraph(self.prototype)
        assert fp.matches('foo/bar.cc')
        assert fp.matches('Makefile')
        assert fp.matches('debian/rules')

        fp.files = ['debian/*']   # type: ignore
        assert not fp.matches('foo/bar.cc')
        assert not fp.matches('Makefile')
        assert fp.matches('debian/rules')

        fp.files = ['Makefile', 'foo/*']   # type: ignore
        assert fp.matches('foo/bar.cc')
        assert fp.matches('Makefile')
        assert not fp.matches('debian/rules')

    @no_type_check
    def test_create(self):
        # type: () -> None
        fp = copyright.FilesParagraph.create(
            files=['Makefile', 'foo/*'],
            copyright='Copyright 2014 Some Guy',
            license=copyright.License('ISC'))
        assert ('Makefile', 'foo/*') == fp.files
        assert 'Copyright 2014 Some Guy' == fp.copyright
        assert copyright.License('ISC') == fp.license

        with pytest.raises(TypeError):
            copyright.FilesParagraph.create(
                files=['*'], copyright='foo', license=None)

        with pytest.raises(TypeError):
            copyright.FilesParagraph.create(
                files=['*'], copyright=None, license=copyright.License('ISC'))

        with pytest.raises(TypeError):
            copyright.FilesParagraph.create(
                files=None, copyright='foo', license=copyright.License('ISC'))


class TestHeader:

    @no_type_check
    def test_format_not_none(self):
        # type: () -> None
        h = copyright.Header()
        assert FORMAT == h.format
        with pytest.raises(TypeError, match='value must not be None'):
            h.format = None

    def test_format_upgrade_no_header(self):
        # type: () -> None
        data = Deb822ParagraphElement.new_empty_paragraph()
        with pytest.raises(copyright.NotMachineReadableError):
            copyright.Header(data=data)

    def test_format_https_upgrade(self, caplog):
        # type: (pytest.LogCaptureFixture) -> None
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Format'] = "http%s" % FORMAT[5:]
        with caplog.at_level(logging.WARNING):
            h = copyright.Header(data=data)
        assert caplog.record_tuples == [(
            "debian.copyright",
            logging.WARNING,
            'Fixing Format URL'
        )]
        assert FORMAT == h.format  # type: ignore

    @no_type_check
    def test_upstream_name_single_line(self):
        # type: () -> None
        h = copyright.Header()
        h.upstream_name = 'Foo Bar'
        assert 'Foo Bar' == h.upstream_name
        with pytest.raises(ValueError, match='must be single line'):
            h.upstream_name = 'Foo Bar\n Baz'

    def test_upstream_contact_single_read(self):
        # type: () -> None
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Format'] = FORMAT
        data['Upstream-Contact'] = 'Foo Bar <foo@bar.com>'
        h = copyright.Header(data=data)
        assert ('Foo Bar <foo@bar.com>',) == h.upstream_contact  # type: ignore

    def test_upstream_contact_multi1_read(self):
        # type: () -> None
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Format'] = FORMAT
        data['Upstream-Contact'] = 'Foo Bar <foo@bar.com>\n http://bar.com/foo'
        h = copyright.Header(data=data)
        assert ('Foo Bar <foo@bar.com>', 'http://bar.com/foo') == \
            h.upstream_contact   # type: ignore

    def test_upstream_contact_multi2_read(self):
        # type: () -> None
        data = Deb822ParagraphElement.new_empty_paragraph()
        data['Format'] = FORMAT
        data['Upstream-Contact'] = (
            '\n Foo Bar <foo@bar.com>\n http://bar.com/foo')
        h = copyright.Header(data=data)
        assert ('Foo Bar <foo@bar.com>', 'http://bar.com/foo') == \
            h.upstream_contact  # type: ignore

    def test_upstream_contact_single_write(self):
        # type: () -> None
        h = copyright.Header()
        h.upstream_contact = ['Foo Bar <foo@bar.com>']   # type: ignore
        assert ('Foo Bar <foo@bar.com>',) == h.upstream_contact  # type: ignore
        assert 'Foo Bar <foo@bar.com>' == h['Upstream-Contact']

    def test_upstream_contact_multi_write(self):
        # type: () -> None
        h = copyright.Header()
        h.upstream_contact = ['Foo Bar <foo@bar.com>', 'http://bar.com/foo']   # type: ignore
        assert ('Foo Bar <foo@bar.com>', 'http://bar.com/foo') == \
            h.upstream_contact  # type: ignore
        assert '\n Foo Bar <foo@bar.com>\n http://bar.com/foo' == \
            h['upstream-contact']

    def test_license(self):
        # type: () -> None
        h = copyright.Header()
        assert h.license is None
        l = copyright.License('GPL-2+')
        h.license = l
        assert l == h.license
        assert 'GPL-2+' == h['license']

        h.license = None
        assert h.license is None
        assert not ('license' in h)


def _no_space(s):
    # type: (str) -> str
    """Returns s.  Raises ValueError if s contains any whitespace."""
    if re.search(r'\s', s):
        raise ValueError('whitespace not allowed')
    return s
