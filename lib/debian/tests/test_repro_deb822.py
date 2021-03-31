#!/usr/bin/python3
# -*- coding: utf-8 -*- vim: fileencoding=utf-8 :

# Copyright (C) 2021 Niels Thykier
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

"""Tests for format preserving deb822"""
import collections
import sys
import textwrap
from unittest import TestCase, SkipTest

if sys.version_info >= (3, 9):
    from debian._deb822_repro import parse_deb822_file, Deb822ErrorToken
else:
    parse_deb822_file = None
    Deb822ErrorToken = None

RoundTripParseCase = collections.namedtuple('RoundTripParseCase',
                                            ['input',
                                             'is_valid_file',
                                             'error_element_count',
                                             'paragraph_count',
                                             ])

# We use ¶ as "end of line" marker for two reasons in cases with optional whitespace:
# - to show that we have it when you debug the test case
# - to stop formatters from stripping it
#
# The marker is not required.  Consider to omit it if the test case does not
# involve trailing whitespace.
#
# NB: As a side-effect of the implementation, the tests strips '¶' unconditionally.
# Please another fancy glyph if you need to test non-standard characters.
ROUND_TRIP_CASES = [
    RoundTripParseCase(input='',
                       is_valid_file=False,
                       error_element_count=0,
                       paragraph_count=0
                       ),
    RoundTripParseCase(input='A: b',
                       is_valid_file=True,
                       error_element_count=0,
                       paragraph_count=1
                       ),
    RoundTripParseCase(input=textwrap.dedent('''\
                        Source: debhelper
                        # Trailing-whitespace
                        # Comment before a field
                        Build-Depends: po4a

                        #  Comment about debhelper
                        Package: debhelper
                        Architecture: all
                        Depends: something
                        # We also depend on libdebhelper-perl
                                 libdebhelper-perl (= ${binary:Version})
                        Description: something
                         A long
                         and boring
                         description
                        # And a continuation line (also, inline comment)
                         .
                         Final remark
                        # Comment at the end of a paragraph plus multiple empty lines



                        # This paragraph contains a lot of trailing-whitespace cases, so we¶
                        # will be using the end of line marker through out this paragraph  ¶
                        Package: libdebhelper-perl¶
                        Priority:optional ¶
                        Section:   section   ¶
                        #   Field starting  with     a space + newline (special-case)¶
                        Depends:¶
                                 ${perl:Depends},¶
                        # Some people like the "leading comma" solution to dependencies¶
                        # so we should we have test case for that as well.¶
                        # (makes more sense when we start to parse the field as a dependency¶
                        # field)¶
                        Suggests: ¶
                                , something  ¶
                                , another¶
                        # Field that ends without a newline¶
                        Architecture: all¶'''),
                       paragraph_count=3,
                       is_valid_file=True,
                       error_element_count=0,
                       ),
    RoundTripParseCase(input=textwrap.dedent('''\
                        Source: debhelper
                        # Missing colon
                        Build-Depends po4a

                        #  Comment about debhelper
                        Package: debhelper
                        Depends: something
                        # We also depend on libdebhelper-perl
                                 libdebhelper-perl (= ${binary:Version})
                        Description: something
                         A long
                         and boring
                         description
                        # Missing the dot

                         Final remark


                        Package: libdebhelper-perl
                        '''),
                       paragraph_count=3,
                       is_valid_file=False,
                       error_element_count=2,
                       ),
    RoundTripParseCase(input=textwrap.dedent('''\
                        A: b
                        B: c
                        # Duplicate field
                        A: b
                        '''),
                       is_valid_file=False,
                       error_element_count=0,
                       paragraph_count=1
                       ),
    RoundTripParseCase(input=textwrap.dedent('''\
                    Is-Valid-Paragraph: yes

                    Is-Valid-Paragraph: Definitely not
                    Package: foo
                    Package: bar
                    Something-Else:
                    # Some comment
                     asd
                    Package: baz
                    Another-Field: foo
                    Package: again
                    I-Can-Haz-Package: ?
                    Package: yes
                    '''),
                       is_valid_file=False,
                       error_element_count=0,
                       paragraph_count=2
                       ),
]


class FormatPreservingDeb822ParserTests(TestCase):

    def test_round_trip_cases(self):
        # type: () -> None

        if sys.version_info < (3, 9):
            raise SkipTest('The format preserving parser assume python 3.9')

        for i, parse_case in enumerate(ROUND_TRIP_CASES, start=1):
            c = str(i)
            case_input = parse_case.input.replace('¶', '')
            try:
                deb822_file = parse_deb822_file(case_input.splitlines(keepends=True))
            except Exception:
                print("Error while parsing case " + c)
                raise
            error_element_count = 0
            for token in deb822_file.iter_tokens():
                if isinstance(token, Deb822ErrorToken):
                    error_element_count += 1
            paragraphs = len(list(deb822_file.paragraphs))
            # Remember you can use _print_ast(deb822_file) if you need to debug the test cases.
            # A la
            #
            # if i in (3, 4):
            #   print(f" ---  CASE {i} --- ")
            #   _print_ast(deb822_file)
            #   print(f" ---  END CASE {i} --- ")
            self.assertEqual(parse_case.error_element_count, error_element_count,
                             "Correct number of error tokens for case " + c)
            self.assertEqual(parse_case.paragraph_count, paragraphs,
                             "Correct number of paragraphs parsed for case " + c)
            self.assertEqual(parse_case.is_valid_file, deb822_file.is_valid_file,
                             "Verify deb822_file correctly determines whether the field is invalid"
                             " for case " + c)
            self.assertEqual(case_input, deb822_file.convert_to_text(),
                             "Input of case " + c + " is round trip safe")
            print("Successfully passed case " + c)
