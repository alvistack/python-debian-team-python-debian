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
import contextlib
import logging
import textwrap
from debian.deb822 import Deb822

import pytest

from debian._deb822_repro import (parse_deb822_file,
                                  AmbiguousDeb822FieldKeyError,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  Interpretation,
                                  )
from debian._deb822_repro.parsing import Deb822KeyValuePairElement, Deb822ParsedTokenList, Deb822ParagraphElement, \
    Deb822FileElement, Deb822ParsedValueElement, LIST_UPLOADERS_INTERPRETATION
from debian._deb822_repro.tokens import Deb822Token, Deb822ErrorToken
from debian._deb822_repro._util import print_ast

try:
    from typing import Any, Iterator, Tuple
    from debian._deb822_repro.types import VE, ST
except ImportError:
    pass

RoundTripParseCase = collections.namedtuple('RoundTripParseCase',
                                            ['input',
                                             'is_valid_file',
                                             'error_element_count',
                                             'duplicate_fields',
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
    RoundTripParseCase(input='\n',
                       is_valid_file=False,
                       error_element_count=0,
                       duplicate_fields=False,
                       paragraph_count=0
                       ),
    RoundTripParseCase(input='A: b\n',
                       is_valid_file=True,
                       error_element_count=0,
                       duplicate_fields=False,
                       paragraph_count=1
                       ),
    RoundTripParseCase(input=textwrap.dedent('''\
                        Source: debhelper
                        # Trailing-whitespace
                        # Comment before a field
                        Build-Depends: po4a
                        # Ending with an empty field
                        Empty-Field:
                        '''),
                       is_valid_file=True,
                       error_element_count=0,
                       duplicate_fields=False,
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
                        \tand boring
                         description
                        # And a continuation line (also, inline comment)
                         .
                         Final remark
                        # Comment at the end of a paragraph plus multiple empty lines



                        # This paragraph contains a lot of trailing-whitespace cases, so we¶
                        # will be using the end of line marker through out this paragraph  ¶
                        Package: libdebhelper-perl¶
                        Priority:optional ¶
                        # Allowed for debian/control file
                        Empty-Field:¶
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
                        Architecture: all¶
                        '''),
                       paragraph_count=3,
                       is_valid_file=True,
                       duplicate_fields=False,
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
                       duplicate_fields=False,
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
                       duplicate_fields=True,
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
                       duplicate_fields=True,
                       paragraph_count=2
                       ),
]



class TestFormatPreservingDeb822Parser:

    def test_round_trip_cases(self):
        # type: () -> None

        for i, parse_case in enumerate(ROUND_TRIP_CASES, start=1):
            c = str(i)
            case_input = parse_case.input.replace('¶', '')
            try:
                deb822_file = parse_deb822_file(case_input.splitlines(keepends=True),
                                                accept_files_with_duplicated_fields=True,
                                                accept_files_with_error_tokens=True,
                                                )
            except Exception:
                logging.info("Error while parsing case " + c)
                raise
            error_element_count = 0
            for token in deb822_file.iter_tokens():
                if isinstance(token, Deb822ErrorToken):
                    error_element_count += 1

            if parse_case.error_element_count > 0 or parse_case.duplicate_fields:
                with pytest.raises(ValueError):
                    # By default, we would reject this file.
                    parse_deb822_file(case_input.splitlines(keepends=True))
            else:
                # The field should be accepted without any errors by default
                parse_deb822_file(case_input.splitlines(keepends=True))

            paragraph_count = len(list(deb822_file))
            # Remember you can use _print_ast(deb822_file) if you need to debug the test cases.
            # A la
            #
            # if i in (3, 4):
            #   logging.info(f" ---  CASE {i} --- ")
            #   _print_ast(deb822_file)
            #   logging.info(f" ---  END CASE {i} --- ")
            assert parse_case.error_element_count == error_element_count, \
                "Correct number of error tokens for case " + c
            assert parse_case.paragraph_count == paragraph_count, \
                "Correct number of paragraphs parsed for case " + c
            assert parse_case.is_valid_file == deb822_file.is_valid_file, \
                "Verify deb822_file correctly determines whether the field is invalid" \
                " for case " + c
            assert case_input == deb822_file.convert_to_text(), \
                             "Input of case " + c + " is round trip safe"

            newline_normalized_by_omission = parse_deb822_file(
                case_input.splitlines(),
                accept_files_with_duplicated_fields=True,
                accept_files_with_error_tokens=True,
            )
            case_input_newline_normalized = case_input.replace("\r", "")
            if not case_input_newline_normalized.endswith("\n") and len(case_input_newline_normalized.splitlines()) > 1:
                case_input_newline_normalized += "\n"
            assert case_input_newline_normalized == \
                             newline_normalized_by_omission.convert_to_text(), \
                             "Input of case " + c + " is newline normalized round trip safe" \
                                                    " with newlines omitted"
            logging.info("Successfully passed case " + c)

    def test_deb822_emulation(self):
        # type: () -> None

        for i, parse_case in enumerate(ROUND_TRIP_CASES, start=1):
            if not parse_case.is_valid_file:
                continue
            c = str(i)
            case_input = parse_case.input.replace('¶', '')
            try:
                deb822_file = parse_deb822_file(case_input.splitlines(keepends=True))
            except Exception:
                logging.info("Error while parsing case " + c)
                raise
            deb822_paragraphs = list(Deb822.iter_paragraphs(case_input.splitlines()))

            for repro_paragraph, deb822_paragraph in zip(deb822_file, deb822_paragraphs):
                assert list(repro_paragraph) == list(deb822_paragraph), \
                    "Ensure keys are the same and in the correct order, case " + c
                # Use the key from Deb822 as it is compatible with the round safe version
                # (the reverse is not true typing wise)
                for k, ev in deb822_paragraph.items():
                    av = repro_paragraph[k]
                    assert av == ev, "Ensure value for " + k + " is the same, case " + c

    def test_regular_fields(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          # Comment for S-V
          Standards-Version: 1.2.3
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        source_paragraph = next(iter(deb822_file))
        assert "foo" == source_paragraph['Source']
        assert "1.2.3" == source_paragraph['Standards-Version']
        assert "no" == source_paragraph['Rules-Requires-Root']

        # Test setter and deletion while we are at it
        source_paragraph["Rules-Requires-Root"] = "binary-targets"
        source_paragraph["New-Field"] = "value"
        del source_paragraph["Standards-Version"]

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: binary-targets
          New-Field: value
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

        # As an alternative, we can also fix the problem if we discard comments
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))
        as_dict_discard_comments = source_paragraph.configured_view(
            preserve_field_comments_on_field_updates=False,
            auto_resolve_ambiguous_fields=False,
        )
        # Test setter and deletion while we are at it
        as_dict_discard_comments["Rules-Requires-Root"] = "binary-targets"
        as_dict_discard_comments["New-Field"] = "value"
        del as_dict_discard_comments["Standards-Version"]
        expected = textwrap.dedent('''\
          Source: foo
          Rules-Requires-Root: binary-targets
          New-Field: value
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while but discarded comments"

        source_paragraph['Multi-Line-Field-Space'] = textwrap.dedent('''\
        foo
         bar
        ''')
        source_paragraph['Multi-Line-Field-Tab'] = textwrap.dedent('''\
        foo
        \tbar
        ''')
        expected = textwrap.dedent('''\
          Source: foo
          Rules-Requires-Root: binary-targets
          New-Field: value
          Multi-Line-Field-Space: foo
           bar
          Multi-Line-Field-Tab: foo
          \tbar
          ''')
        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving space + tab"

    def test_empty_fields(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          Field: foo
          Empty-Field:''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        source_paragraph = next(iter(deb822_file))
        assert "" == source_paragraph['Empty-Field']
        source_paragraph['Another-Empty-Field'] = ""
        assert "" == source_paragraph['Another-Empty-Field']
        list_view = source_paragraph.as_interpreted_dict_view(LIST_SPACE_SEPARATED_INTERPRETATION)
        with list_view['Empty-Field'] as empty_field:
            assert not bool(empty_field)

        with list_view['Field'] as field:
            assert bool(field)
            field.clear()
            assert not bool(field)

        expected = textwrap.dedent('''\
          Source: foo
          Field:
          Empty-Field:
          Another-Empty-Field:
          ''')
        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked and generate a valid file"

    def test_empty_fields_reorder(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          Field: foo
          Empty-Field:''')
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))
        source_paragraph.order_last('Field')
        expected = textwrap.dedent('''\
          Source: foo
          Empty-Field:
          Field: foo
          ''')
        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked and generate a valid file"
        # Re-parse
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))
        source_paragraph.order_first('Empty-Field')
        expected = textwrap.dedent('''\
          Empty-Field:
          Source: foo
          Field: foo
          ''')
        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked and generate a valid file"

    def test_case_preservation(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          rules-requires-root: no
          # Comment for S-V
          Standards-Version: 1.2.3
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        source_paragraph = next(iter(deb822_file))
        assert "foo" == source_paragraph['Source']
        assert "1.2.3" == source_paragraph['Standards-Version']
        assert "no" == source_paragraph['Rules-Requires-Root']

        # Test setter and deletion while we are at it
        source_paragraph["Rules-Requires-Root"] = "binary-targets"
        source_paragraph["New-field"] = "value"
        del source_paragraph["Standards-Version"]

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          rules-requires-root: binary-targets
          New-field: value
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving case"

        # Repeat with duplicated fields
        original = textwrap.dedent('''\
          source: foo
          source: foo
          # Comment for RRR
          rules-requires-root: no
          rules-requires-root: no
          # Comment for S-V
          Standards-Version: 1.2.3
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True),
                                        accept_files_with_duplicated_fields=True,
                                        )

        source_paragraph = next(iter(deb822_file))
        assert "foo" == source_paragraph['Source']
        assert "1.2.3" == source_paragraph['Standards-Version']
        assert "no" == source_paragraph['Rules-Requires-Root']

        # Test setter and deletion while we are at it
        source_paragraph["Rules-Requires-Root"] = "binary-targets"
        source_paragraph["New-field"] = "value"
        del source_paragraph["Standards-Version"]

        expected = textwrap.dedent('''\
          source: foo
          source: foo
          # Comment for RRR
          rules-requires-root: binary-targets
          New-field: value
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving case"

    def test_preserve_field_order_on_mutation(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          Section: bar
          Priority: extra
          # Comment for RRR
          Rules-Requires-Root: no
          Build-Depends: debhelper-compat (= 10)
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        source_paragraph = next(iter(deb822_file))
        assert "foo" == source_paragraph['Source']

        source_paragraph["Rules-Requires-Root"] = "binary-targets"
        source_paragraph["section"] = "devel"
        source_paragraph["Priority"] = "optional"

        expected = textwrap.dedent('''\
          Source: foo
          Section: devel
          Priority: optional
          # Comment for RRR
          Rules-Requires-Root: binary-targets
          Build-Depends: debhelper-compat (= 10)
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving field order"

        # Again - this time with a paragraph containing duplicate fields
        original = textwrap.dedent('''\
          Source: foo
          Source: foo2
          Section: bar
          Section: baz
          Priority: extra
          # Comment for RRR
          Rules-Requires-Root: no
          Build-Depends: debhelper-compat (= 10)
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True),
                                        accept_files_with_duplicated_fields=True,
                                        )

        source_paragraph = next(iter(deb822_file))
        assert "foo" == source_paragraph['Source']

        source_paragraph["Rules-Requires-Root"] = "binary-targets"
        source_paragraph["section"] = "devel"
        source_paragraph["Priority"] = "optional"

        expected = textwrap.dedent('''\
          Source: foo
          Source: foo2
          Section: devel
          Priority: optional
          # Comment for RRR
          Rules-Requires-Root: binary-targets
          Build-Depends: debhelper-compat (= 10)
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving field order"

    def test_preserve_field_case_on_iter(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          secTion: bar
          PrIorIty: extra
          # Comment for RRR
          Rules-Requires-Root: no
          Build-Depends: debhelper-compat (= 10)
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        source_paragraph = next(iter(deb822_file))
        expected_keys = {
            'Source',
            'secTion',
            'PrIorIty',
            'Rules-Requires-Root',
            'Build-Depends'
        }
        actual_keys = set(source_paragraph.keys())

        assert expected_keys == actual_keys, \
            "Keys returned by iterations should have original case"

    def test_append_paragraph(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'bar'
        binary_paragraph['Description'] = 'Binary package bar'

        deb822_file.append(binary_paragraph)

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          Package: bar
          Description: Binary package bar
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_append_paragraph_existing_trailing_newline(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'bar'
        binary_paragraph['Description'] = 'Binary package bar'

        deb822_file.append(binary_paragraph)

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          Package: bar
          Description: Binary package bar
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_append_empty_paragraph(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()

        deb822_file.append(binary_paragraph)

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_append_tailing_comment(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          # Foo
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'bar'
        binary_paragraph['Description'] = 'Binary package bar'

        deb822_file.append(binary_paragraph)

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          # Foo

          Package: bar
          Description: Binary package bar
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_insert_paragraph(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'bar'
        binary_paragraph['Description'] = 'Binary package bar'

        deb822_file.insert(0, binary_paragraph)

        expected = textwrap.dedent('''\
          Package: bar
          Description: Binary package bar

          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

        # Insert after the existing paragraphs

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'blah'
        binary_paragraph['Description'] = 'Binary package blah'

        deb822_file.insert(5, binary_paragraph)

        expected = textwrap.dedent('''\
          Package: bar
          Description: Binary package bar

          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          Package: blah
          Description: Binary package blah
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_insert_paragraph_with_comments(self):
        # type: () -> None

        # Note that it is unspecified where the "Package: bar"-paragraph is
        # inserted relative to the "# Initial comment"-comment.  This test case
        # only asserts that it does not change unknowingly.

        original = textwrap.dedent('''\
          # Initial comment

          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          # Comment
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'bar'
        binary_paragraph['Description'] = 'Binary package bar'

        deb822_file.insert(0, binary_paragraph)

        expected = textwrap.dedent('''\
          Package: bar
          Description: Binary package bar

          # Initial comment

          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          # Comment
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

        # Insert after the existing paragraphs

        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'blah'
        binary_paragraph['Description'] = 'Binary package blah'

        deb822_file.insert(5, binary_paragraph)

        expected = textwrap.dedent('''\
          Package: bar
          Description: Binary package bar

          # Initial comment

          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          # Comment

          Package: blah
          Description: Binary package blah
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_insert_paragraph_in_empty_file(self):
        # type: () -> None

        deb822_file = Deb822FileElement.new_empty_file()
        binary_paragraph = Deb822ParagraphElement.new_empty_paragraph()
        binary_paragraph['Package'] = 'bar'
        binary_paragraph['Description'] = 'Binary package bar'
        # There is a special-case for idx == 0 and that should be well-behaved
        # for empty files too.
        deb822_file.insert(0, binary_paragraph)

        expected = textwrap.dedent('''\
          Package: bar
          Description: Binary package bar
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_remove_paragraph(self):
        # type: () -> None
        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          Package: bar
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = list(deb822_file)[1]
        assert 'bar' == binary_paragraph['Package']

        deb822_file.remove(binary_paragraph)

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

        # Verify that we can add another paragraph.
        deb822_file.append(Deb822ParagraphElement.from_dict({'Package': 'bloe'}))

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          Package: bloe
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Adding new paragraph should have worked"

        deb822_file.remove(list(deb822_file)[1])

        source_paragraph = list(deb822_file)[0]
        assert 'foo' == source_paragraph['Source']

        deb822_file.remove(source_paragraph)

        expected = textwrap.dedent('''\
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

        original = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          Package: bar

          # Comment

          Package: la
          ''')

        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        binary_paragraph = list(deb822_file)[1]
        assert 'bar' == binary_paragraph['Package']

        deb822_file.remove(binary_paragraph)

        expected = textwrap.dedent('''\
          Source: foo
          # Comment for RRR
          Rules-Requires-Root: no

          # Comment

          Package: la
          ''')

        assert expected == deb822_file.convert_to_text(), \
            "Mutation should have worked while preserving comments"

    def test_duplicate_fields(self):
        # type: () -> None

        original = textwrap.dedent('''\
        Source: foo
        # Comment for RRR
        Rules-Requires-Root: no
        # Comment for S-V
        Standards-Version: 1.2.3
        Rules-Requires-Root: binary-targets
        ''')
        # By default, the file is accepted
        deb822_file = parse_deb822_file(original.splitlines(keepends=True),
                                        accept_files_with_duplicated_fields=True,
                                        )

        with pytest.raises(ValueError):
            # But the parser should raise an error if explicitly requested
            parse_deb822_file(original.splitlines(keepends=True),
                              accept_files_with_error_tokens=True,
                              accept_files_with_duplicated_fields=False,
                              )

        source_paragraph = next(iter(deb822_file))
        as_dict = source_paragraph.configured_view(auto_resolve_ambiguous_fields=False)
        # Non-ambiguous fields are fine
        assert "foo" == as_dict['Source']
        assert "1.2.3" == as_dict['Standards-Version']
        # Contains doesn't raise a AmbiguousDeb822FieldKeyError
        assert 'Rules-Requires-Root' in as_dict
        with pytest.raises(AmbiguousDeb822FieldKeyError):
            v = as_dict['Rules-Requires-Root']
        as_dict_auto_resolve = source_paragraph.configured_view(auto_resolve_ambiguous_fields=True)
        assert "foo" == as_dict_auto_resolve['Source']
        assert "1.2.3" == as_dict_auto_resolve['Standards-Version']
        # Auto-resolution always takes the first field value
        assert "no" == as_dict_auto_resolve['Rules-Requires-Root']
        # It should be possible to "fix" the duplicate field by setting the field explicitly
        as_dict_auto_resolve['Rules-Requires-Root'] = as_dict_auto_resolve['Rules-Requires-Root']

        expected_fixed = original.replace('Rules-Requires-Root: binary-targets\n', '')
        assert expected_fixed == deb822_file.convert_to_text(), \
            "Fixed version should only have one Rules-Requires-Root field"

        # As an alternative, we can also fix the problem if we discard comments
        deb822_file = parse_deb822_file(original.splitlines(keepends=True),
                                        accept_files_with_duplicated_fields=True,
                                        )
        source_paragraph = next(iter(deb822_file))
        as_dict_discard_comments = source_paragraph.configured_view(
            preserve_field_comments_on_field_updates=False,
            auto_resolve_ambiguous_fields=False,
        )
        # First, ensure the reset succeeded
        with pytest.raises(AmbiguousDeb822FieldKeyError):
            v = as_dict_discard_comments['Rules-Requires-Root']
        as_dict_discard_comments["Rules-Requires-Root"] = "no"
        # Test setter and deletion while we are at it
        as_dict_discard_comments["New-Field"] = "value"
        del as_dict_discard_comments["Standards-Version"]
        as_dict_discard_comments['Source'] = 'bar'
        expected = textwrap.dedent('''\
        Source: bar
        Rules-Requires-Root: no
        New-Field: value
        ''')
        assert expected == deb822_file.convert_to_text(), \
            "Fixed version should only have one Rules-Requires-Root field"

    def test_sorting(self):
        # type: () -> None

        name_order = {
            f: i
            for i, f in enumerate([
                'source',
                'priority'
            ], start=0)
        }

        def key_func(field_name):
            # type: (str) -> Tuple[int, str]
            field_name_lower = field_name.lower()
            order = name_order.get(field_name_lower)
            if order is not None:
                return order, field_name_lower
            return len(name_order), field_name_lower

        # Note the lack of trailing newline is deliberate.
        # We want to ensure that sorting cannot trash the file even if the last
        # field does not end with a newline
        original_nodups = textwrap.dedent('''\
        Source: foo
        # Comment for RRR
        Rules-Requires-Root: no
        # Comment for S-V
        Standards-Version: 1.2.3
        Build-Depends: foo
        # With inline comment
                       bar
        Priority: optional''')

        sorted_nodups = textwrap.dedent('''\
        Source: foo
        Priority: optional
        Build-Depends: foo
        # With inline comment
                       bar
        # Comment for RRR
        Rules-Requires-Root: no
        # Comment for S-V
        Standards-Version: 1.2.3
        ''')

        original_with_dups = textwrap.dedent('''\
        Source: foo
        # Comment for RRR
        Rules-Requires-Root: no
        # Comment for S-V
        Standards-Version: 1.2.3
        Priority: optional
        # Comment for Second instance of RRR
        Rules-Requires-Root: binary-targets
        Build-Depends: foo
        # With inline comment
                       bar''')
        sorted_with_dups = textwrap.dedent('''\
        Source: foo
        Priority: optional
        Build-Depends: foo
        # With inline comment
                       bar
        # Comment for RRR
        Rules-Requires-Root: no
        # Comment for Second instance of RRR
        Rules-Requires-Root: binary-targets
        # Comment for S-V
        Standards-Version: 1.2.3
        ''')

        deb822_file_nodups = parse_deb822_file(original_nodups.splitlines(keepends=True))
        for paragraph in deb822_file_nodups:
            paragraph.sort_fields(key=key_func)

        assert sorted_nodups == deb822_file_nodups.convert_to_text(), \
            "Sorting without duplicated fields work"
        deb822_file_with_dups = parse_deb822_file(original_with_dups.splitlines(keepends=True),
                                                  accept_files_with_duplicated_fields=True,
                                                  )

        for paragraph in deb822_file_with_dups:
            paragraph.sort_fields(key=key_func)

        assert sorted_with_dups == deb822_file_with_dups.convert_to_text(), \
            "Sorting with duplicated fields work"

    def test_reorder_nodups(self):
        # type: () -> None
        content = textwrap.dedent("""
        Depends: bar
        Description: some-text
        Architecture: any
        Package: foo
        Recommends: baz
        """)
        deb822_file = parse_deb822_file(content.splitlines(keepends=True))
        paragraph = next(iter(deb822_file))

        # Verify the starting state
        assert list(paragraph.keys()) == \
                         ['Depends', 'Description', 'Architecture', 'Package', 'Recommends']
        # no op
        paragraph.order_last('Recommends')
        assert list(paragraph.keys()) == \
                         ['Depends', 'Description', 'Architecture', 'Package', 'Recommends']
        # no op
        paragraph.order_first('Depends')
        assert list(paragraph.keys()) == \
                         ['Depends', 'Description', 'Architecture', 'Package', 'Recommends']

        paragraph.order_first('Package')
        assert list(paragraph.keys()) == \
                         ['Package', 'Depends', 'Description', 'Architecture', 'Recommends']

        paragraph.order_last('Description')
        assert list(paragraph.keys()) == \
                         ['Package', 'Depends', 'Architecture', 'Recommends', 'Description']

        paragraph.order_after('Recommends', 'Depends')
        assert list(paragraph.keys()) == \
                         ['Package', 'Depends', 'Recommends', 'Architecture', 'Description']

        paragraph.order_before('Architecture', 'Depends')
        assert list(paragraph.keys()) == \
                         ['Package', 'Architecture', 'Depends', 'Recommends', 'Description']

        with pytest.raises(ValueError):
            paragraph.order_after('Architecture', 'Architecture')
        with pytest.raises(ValueError):
            paragraph.order_before('Architecture', 'Architecture')
        with pytest.raises(KeyError):
            paragraph.order_before('Unknown-Field', 'Architecture')
        with pytest.raises(KeyError):
            paragraph.order_before('Architecture', 'Unknown-Field')

    def test_reorder_dups(self):
        # type: () -> None
        content = textwrap.dedent("""
        Depends: bar
        Description: some-text
        Description: some-more-text
        Architecture: any
        Package: foo
        Package: foo2
        Recommends: baz
        """)
        deb822_file = parse_deb822_file(content.splitlines(keepends=True),
                                        accept_files_with_duplicated_fields=True,
                                        )
        paragraph = next(iter(deb822_file))
        # Verify the starting state
        assert list(paragraph.keys()) == \
                         ['Depends', 'Description', 'Description', 'Architecture', 'Package',
                          'Package', 'Recommends']
        # no op
        paragraph.order_last('Recommends')
        assert list(paragraph.keys()) == \
                         ['Depends', 'Description', 'Description', 'Architecture', 'Package',
                          'Package', 'Recommends']
        # no op
        paragraph.order_first('Depends')
        assert list(paragraph.keys()) == \
                         ['Depends', 'Description', 'Description', 'Architecture', 'Package',
                          'Package', 'Recommends']

        paragraph.order_first('Package')
        assert list(paragraph.keys()) == \
                         ['Package', 'Package','Depends', 'Description', 'Description',
                          'Architecture', 'Recommends']

        # Relative order must be preserved in this case.
        assert paragraph["Package"] == "foo"
        assert paragraph[("Package", 0)] == "foo"
        assert paragraph[("Package", 1)] == "foo2"

        # Repeating order_first should be a noop
        paragraph.order_first('Package')
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Depends', 'Description', 'Description',
                          'Architecture', 'Recommends']

        # Relative order must be preserved in this case.
        assert paragraph["Package"] == "foo"
        assert paragraph[("Package", 0)] == "foo"
        assert paragraph[("Package", 1)] == "foo2"

        paragraph.order_last('Description')
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Depends', 'Architecture', 'Recommends',
                          'Description', 'Description']
        # Relative order must be preserved in this case.
        assert paragraph["Description"] == "some-text"
        assert paragraph[("Description", 0)] == "some-text"
        assert paragraph[("Description", 1)] == "some-more-text"

        # Repeating order_first should be a noop
        paragraph.order_last('Description')
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Depends', 'Architecture', 'Recommends',
                          'Description', 'Description']
        # Relative order must be preserved in this case.
        assert paragraph["Description"] == "some-text"
        assert paragraph[("Description", 0)] == "some-text"
        assert paragraph[("Description", 1)] == "some-more-text"

        paragraph.order_after('Recommends', 'Depends')
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Depends', 'Recommends', 'Architecture',
                          'Description', 'Description', ]

        paragraph.order_before('Architecture', 'Depends')
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]

        # And now, for some "fun stuff"

        # Lets move the last Description field in front of the first.
        paragraph.order_before(('Description', 1), ('Description', 0))
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]
        # Verify the relocation was successful
        assert paragraph["Description"] == "some-more-text"
        assert paragraph[("Description", 0)] == "some-more-text"
        assert paragraph[("Description", 1)] == "some-text"

        # And swap their relative positions again
        paragraph.order_after(('Description', 0), ('Description', 1))
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]
        # Verify the relocation was successful
        assert paragraph["Description"] == "some-text"
        assert paragraph[("Description", 0)] == "some-text"
        assert paragraph[("Description", 1)] == "some-more-text"

        # This should be a no-op
        paragraph.order_last(('Description', 1))
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]
        assert paragraph["Description"] == "some-text"
        assert paragraph[("Description", 0)] == "some-text"
        assert paragraph[("Description", 1)] == "some-more-text"

        # This should cause them to swap order
        paragraph.order_last(('Description', 0))
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]
        # Verify the relocation was successful
        assert paragraph["Description"] == "some-more-text"
        assert paragraph[("Description", 0)] == "some-more-text"
        assert paragraph[("Description", 1)] == "some-text"

        # This should be a no-op
        paragraph.order_first(('Package', 0))
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]

        # Relative order must be preserved in this case.
        assert paragraph["Package"] == "foo"
        assert paragraph[("Package", 0)] == "foo"
        assert paragraph[("Package", 1)] == "foo2"

        # This should cause them to swap order
        paragraph.order_first(('Package', 1))
        assert list(paragraph.keys()) == \
                         ['Package', 'Package', 'Architecture', 'Depends', 'Recommends',
                          'Description', 'Description', ]

        # Verify the relocation was successful
        assert paragraph["Package"] == "foo2"
        assert paragraph[("Package", 0)] == "foo2"
        assert paragraph[("Package", 1)] == "foo"

        with pytest.raises(ValueError):
            paragraph.order_after('Architecture', 'Architecture')
        with pytest.raises(ValueError):
            paragraph.order_before('Architecture', 'Architecture')
        with pytest.raises(KeyError):
            paragraph.order_before('Unknown-Field', 'Architecture')
        with pytest.raises(KeyError):
            paragraph.order_before('Architecture', 'Unknown-Field')

    def test_interpretation(self):
        # type: () -> None

        original = textwrap.dedent('''\
        Package: foo
        Architecture: amd64  i386
        # Also on kfreebsd
          kfreebsd-amd64  kfreebsd-i386
        # With leading comma :)
        Some-Comma-List: , a,  b , c d, e
        Multiline-Comma-List: some
        # Invisible drive by comment
          , fun ,with
          multi-line
        # With a comment inside it for added fun
          values
          ,
        # Also an invisible comment here
          separated by
           ,commas
        # Comments in final value
             >:)
        Uploaders: Someone <nobody@example.org>,
        # Comment that should not be visible in the list
          Margrete, I, Ruler <1@margrete.dk>
        # Some remark that should not be visible in the list even though
        # the comma is on the other side
          ,
          Margrete, II, Queen
        # We could list additional names here
          <2@margrete.dk>
        ''')
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))

        @contextlib.contextmanager
        def _field_mutation_test(
                kvpair,           # type: Deb822KeyValuePairElement
                interpretation,   # type: Interpretation[Deb822ParsedTokenList[VE, ST]]
                expected_output,  # type: str
                ):
            # type: (...) -> Iterator[Deb822ParsedTokenList[VE, ST]]
            original_value_element = kvpair.value_element
            with kvpair.interpret_as(interpretation) as value_list:
                yield value_list

            # We always match without the field comment to keep things simple.
            actual = kvpair.field_name + ":" + kvpair.value_element.convert_to_text()
            try:
                assert expected_output == actual
            except AssertionError:
                logging.info(" -- Debugging aid - START of AST for generated value --")
                print_ast(kvpair)
                logging.info(" -- Debugging aid - END of AST for generated value --")
                raise
            # Reset of value
            kvpair.value_element = original_value_element
            assert original == deb822_file.convert_to_text()

        arch_kvpair = source_paragraph.get_kvpair_element('Architecture')
        comma_list_kvpair = source_paragraph.get_kvpair_element('Some-Comma-List')
        multiline_comma_list_kvpair = source_paragraph.get_kvpair_element('Multiline-Comma-List')
        uploaders_kvpair = source_paragraph.get_kvpair_element('Uploaders')
        assert arch_kvpair is not None and comma_list_kvpair is not None \
            and multiline_comma_list_kvpair is not None and uploaders_kvpair is not None
        archs = arch_kvpair.interpret_as(LIST_SPACE_SEPARATED_INTERPRETATION)
        comma_list_misread = comma_list_kvpair.interpret_as(
            LIST_SPACE_SEPARATED_INTERPRETATION
        )
        assert ['amd64', 'i386', 'kfreebsd-amd64', 'kfreebsd-i386'] == \
                         list(archs)
        assert [',', 'a,', 'b', ',', 'c', 'd,', 'e'] == \
                         list(comma_list_misread)

        comma_list_correctly_read = comma_list_kvpair.interpret_as(
            LIST_COMMA_SEPARATED_INTERPRETATION
        )
        ml_comma_list = multiline_comma_list_kvpair.interpret_as(
            LIST_COMMA_SEPARATED_INTERPRETATION
        )
        ml_comma_list_w_comments = multiline_comma_list_kvpair.interpret_as(
            LIST_COMMA_SEPARATED_INTERPRETATION,
            discard_comments_on_read=False
        )
        uploaders_list = uploaders_kvpair.interpret_as(
            LIST_UPLOADERS_INTERPRETATION,
        )
        uploaders_list_with_comments = uploaders_kvpair.interpret_as(
            LIST_UPLOADERS_INTERPRETATION,
            discard_comments_on_read=False
        )

        assert list(comma_list_correctly_read) == ['a', 'b', 'c d', 'e']

        assert list(ml_comma_list) == [
            "some",
            "fun",
            "with\n  multi-line\n  values",
            "separated by",
            "commas\n     >:)"
        ]

        assert list(ml_comma_list_w_comments) == [
            "some",
            "fun",
            "with\n  multi-line\n# With a comment inside it for added fun\n  values",
            "separated by",
            "commas\n# Comments in final value\n     >:)"
        ]

        assert list(uploaders_list) == [
            "Someone <nobody@example.org>",
            "Margrete, I, Ruler <1@margrete.dk>",
            "Margrete, II, Queen\n  <2@margrete.dk>",
        ]

        assert list(uploaders_list_with_comments) == [
            "Someone <nobody@example.org>",
            "Margrete, I, Ruler <1@margrete.dk>",
            "Margrete, II, Queen\n# We could list additional names here\n  <2@margrete.dk>",
        ]


        # Interpretation must not change the content
        assert original == deb822_file.convert_to_text()

        # But we can choose to modify the content
        expected_result = 'Some-Comma-List: , a,  b , c d, e, f,g,\n'
        with _field_mutation_test(comma_list_kvpair,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  expected_result) as comma_list:
            comma_list.no_reformatting_when_finished()
            comma_list.append('f')
            # We can also omit the space after a separator
            comma_list.append_separator(space_after_separator=False)
            comma_list.append('g')
            comma_list.append_separator(space_after_separator=False)

        # ... and this time we reformat to make it look nicer
        expected_result = textwrap.dedent('''\
            Some-Comma-List: a,
                             c d,
                             e,
            # Something important about "f"
            #
            # ... that spans multiple lines    ¶
                             f,
        ''').replace('¶', '')
        with _field_mutation_test(comma_list_kvpair,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  expected_result) as comma_list:
            comma_list.reformat_when_finished()
            comma_list.append_comment('Something important about "f"')
            comma_list.append_comment('')
            # We can control spacing by explicitly using "#" and "\n"
            comma_list.append_comment('# ... that spans multiple lines    \n')
            comma_list.append('f')
            comma_list.remove('b')

        # If we choose the wrong type of interpretation, the result should still be a valid Deb822 file
        # (even if the contents gets a bit wrong).
        expected_result = textwrap.dedent('''\
             Some-Comma-List: ,
                              a,
                              b
                              ,
                              c
                              d,
                              e
                              f
             ''')
        with _field_mutation_test(comma_list_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as comma_list_misread:
            comma_list_misread.reformat_when_finished()
            comma_list_misread.append('f')

        # This method also preserves existing comments
        expected_result = textwrap.dedent('''\
             Architecture: amd64  i386
             # Also on kfreebsd
               kfreebsd-amd64  kfreebsd-i386
             # And now on hurd
              hurd-amd64
              hurd-i386
             ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            arch_list.append_comment("And now on hurd")
            arch_list.append('hurd-amd64')
            arch_list.append_newline()
            arch_list.append('hurd-i386')

        # ... removals and comments
        expected_result = textwrap.dedent('''\
             Architecture: amd64  linux-x32
             # And now on hurd
              hurd-amd64
                 ''')

        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            arch_list.append_comment("And now on hurd")
            arch_list.append('hurd-amd64')
            arch_list.remove('kfreebsd-amd64')
            arch_list.remove('kfreebsd-i386')
            arch_list.replace('i386', 'linux-x32')

        # Reformatting will also preserve comments
        expected_result = textwrap.dedent('''\
             Architecture: amd64
                           i386
             # Also on kfreebsd
                           kfreebsd-amd64
                           kfreebsd-i386
             # And now on hurd
                           hurd-amd64
                           hurd-i386
             ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.reformat_when_finished()
            arch_list.append_newline()
            arch_list.append_comment("And now on hurd")
            arch_list.append('hurd-amd64')
            arch_list.append('hurd-i386')

        # Test removals of first and last value
        expected_result = textwrap.dedent('''\
            Architecture: i386
            # Also on kfreebsd
              kfreebsd-amd64¶
                 ''').replace('¶', '')

        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            arch_list.remove('amd64')
            arch_list.remove('kfreebsd-i386')

        # Same, just using value references
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            for value_ref in arch_list.iter_value_references():
                if value_ref.value in ('amd64', 'kfreebsd-i386'):
                    value_ref.remove()
                    # Ensure that a second call fails
                    with pytest.raises(RuntimeError):
                        value_ref.remove()

                    # As does attempting to fetch the value
                    with pytest.raises(RuntimeError):
                        _ = value_ref.value

                    # As does attempting to mutate the value
                    with pytest.raises(RuntimeError):
                        value_ref.value = "foo"

        expected_result = textwrap.dedent('''\
            Architecture: linux-amd64  linux-i386
            # Also on kfreebsd
              kfreebsd-amd64  kfreebsd-i386
        ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            for value_ref in arch_list.iter_value_references():
                value = value_ref.value
                if '-' not in value:
                    value_ref.value = 'linux-' + value

        # Test removal of first line without comment will hoist up the next line
        # - note eventually we might support keeping the comment by doing a
        #   "\n# ...\n value".
        expected_result = textwrap.dedent('''\
            Architecture: kfreebsd-amd64  kfreebsd-i386
                 ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            arch_list.remove('amd64')
            arch_list.remove('i386')

        # Test removal of first line without comment will hoist up the next line
        # This is only similar to the previous test case because we have not
        # made the previous case preserve comments
        expected_result = textwrap.dedent('''\
            Architecture: hurd-amd64
                 ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            # Delete kfreebsd first (which will remove the comment)
            arch_list.remove('kfreebsd-i386')
            arch_list.remove('kfreebsd-amd64')
            arch_list.append_newline()
            arch_list.append('hurd-amd64')
            arch_list.remove('amd64')
            arch_list.remove('i386')

        # Test deletion of the last value, which will clear the field
        expected_result = textwrap.dedent('''\
            Architecture: hurd-amd64
                 ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.no_reformatting_when_finished()
            arch_list.append_comment("This will not appear in the output")
            assert arch_list
            arch_list.remove('kfreebsd-i386')
            arch_list.remove('kfreebsd-amd64')
            arch_list.remove('amd64')
            arch_list.remove('i386')
            # Field should be cleared now.
            assert not arch_list
            # Add a value (as leaving the field empty would raise an error
            # on leaving the with-statement)
            arch_list.append('hurd-amd64')

        # Test sorting of the field
        expected_result = textwrap.dedent('''\
                Architecture: amd64
                              hurd-amd64
                              hurd-i386
                              i386
                # Also on kfreebsd
                              kfreebsd-amd64
                              kfreebsd-i386
                              ppc64el
                 ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            # Sort does not promise a "nice" output, hench reformatting
            arch_list.reformat_when_finished()
            # Add a few extra as the field is "almost" sorted already.
            arch_list.append('ppc64el')
            arch_list.append('hurd-i386')
            arch_list.append('hurd-amd64')
            arch_list.sort()

        # Test sorting of the field with key-func
        expected_result = textwrap.dedent('''\
                Architecture: amd64
                              i386
                              ppc64el
                # Also on kfreebsd
                              kfreebsd-amd64
                              kfreebsd-i386
                # Also on hurd
                              hurd-amd64
                              hurd-i386
                 ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            # Sort does not promise a "nice" output, hench reformatting
            arch_list.reformat_when_finished()
            # Add a few extra as the field is "almost" sorted already.
            arch_list.append('ppc64el')
            arch_list.append('hurd-i386')
            arch_list.append_comment('Also on hurd')
            arch_list.append('hurd-amd64')
            order = {
                'linux': 0,
                'kfreebsd': 1,
                'hurd': 2,
            }

            def _key_func(v):
                # type: (str) -> Any
                if '-' in v:
                    ov = order.get(v.split('-')[0])
                    if ov is None:
                        ov = 0
                else:
                    ov = 0
                return ov, v

            arch_list.sort(key=_key_func)

    def test_interpretation_tab_preservation(self):
        # type: () -> None

        original = textwrap.dedent('''\
        Package: foo
        Architecture: amd64  i386
          kfreebsd-amd64  kfreebsd-i386
        Build-Depends: debhelper-compat (= 12)
        \t , foo
        ''')
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))

        arch_kvpair = source_paragraph.get_kvpair_element('Architecture')
        bd_kvpair = source_paragraph.get_kvpair_element('Build-Depends')
        assert arch_kvpair is not None and bd_kvpair is not None

        @contextlib.contextmanager
        def _field_mutation_test(
                kvpair,           # type: Deb822KeyValuePairElement
                interpretation,   # type: Interpretation[Deb822ParsedTokenList[VE, ST]]
                expected_output,  # type: str
                ):
            # type: (...) -> Iterator[Deb822ParsedTokenList[VE, ST]]
            original_value_element = kvpair.value_element
            with kvpair.interpret_as(interpretation) as value_list:
                yield value_list

            # We always match without the field comment to keep things simple.
            actual = kvpair.field_name + ":" + kvpair.value_element.convert_to_text()
            try:
                assert expected_output == actual
            except AssertionError:
                logging.info(" -- Debugging aid - START of AST for generated value --")
                print_ast(kvpair)
                logging.info(" -- Debugging aid - END of AST for generated value --")
                raise
            # Reset of value
            kvpair.value_element = original_value_element
            assert original == deb822_file.convert_to_text()

        # With reformatting - should use space
        expected_result = textwrap.dedent('''\
                  Architecture: amd64
                                i386
                                kfreebsd-amd64
                                kfreebsd-i386
                                hurd-amd64
                                hurd-i386
                   ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.reformat_when_finished()
            arch_list.append('hurd-amd64')
            arch_list.append('hurd-i386')

        # Without reformatting - should use space
        expected_result = textwrap.dedent('''\
                  Architecture: amd64  i386
                    kfreebsd-amd64  kfreebsd-i386
                   hurd-amd64 hurd-i386
                   ''')
        with _field_mutation_test(arch_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as arch_list:
            arch_list.append_newline()
            arch_list.append('hurd-amd64')
            arch_list.append('hurd-i386')

        # With reformatting - the default formatter uses space
        expected_result = textwrap.dedent('''\
                          Build-Depends: debhelper-compat (= 12),
                                         foo,
                                         bar (>= 1.0~),
                           ''')
        with _field_mutation_test(bd_kvpair,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  expected_result) as bd_list:
            bd_list.reformat_when_finished()
            bd_list.append('bar (>= 1.0~)')

        # Without reformatting - should use tab
        expected_result = textwrap.dedent('''\
                  Build-Depends: debhelper-compat (= 12)
                  \t , foo
                  \t, bar (>= 1.0~)
                   ''')
        with _field_mutation_test(bd_kvpair,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  expected_result) as bd_list:
            bd_list.append_newline()
            bd_list.append('bar (>= 1.0~)')

    def test_mutate_field_preserves_whitespace(self):
        # type: () -> None

        original = textwrap.dedent('''\
        Package: foo
        Build-Depends:
         debhelper-compat (= 11),
         uuid-dev
        ''')
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))
        source_paragraph['Build-Depends'] = source_paragraph['Build-Depends']
        assert original == deb822_file.convert_to_text()

        original = textwrap.dedent('''\
        Package: foo
        Build-Depends: 
         debhelper-compat (= 11),
         uuid-dev
        ''')
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))
        source_paragraph['Build-Depends'] = ' \n debhelper-compat (= 11),\n uuid-dev'
        assert original == deb822_file.convert_to_text()
