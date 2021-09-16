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
import sys
import textwrap
from debian.deb822 import Deb822
from unittest import TestCase, SkipTest

from debian._deb822_repro import (parse_deb822_file,
                                  AmbiguousDeb822FieldKeyError,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  Interpretation,
                                  )
from debian._deb822_repro.parsing import Deb822KeyValuePairElement, Deb822ParsedTokenList
from debian._deb822_repro.tokens import Deb822Token, Deb822ErrorToken
from debian._deb822_repro._util import print_ast

try:
    from typing import Any, Iterator, Tuple
    from debian._deb822_repro.types import VT, ST
except ImportError:
    pass

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

    def setUp(self) -> None:

        if sys.version_info < (3, 9):
            raise SkipTest('The format preserving parser assume python 3.9')

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

            if parse_case.error_element_count > 0:
                with self.assertRaises(ValueError):
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
            self.assertEqual(parse_case.error_element_count, error_element_count,
                             "Correct number of error tokens for case " + c)
            self.assertEqual(parse_case.paragraph_count, paragraph_count,
                             "Correct number of paragraphs parsed for case " + c)
            self.assertEqual(parse_case.is_valid_file, deb822_file.is_valid_file,
                             "Verify deb822_file correctly determines whether the field is invalid"
                             " for case " + c)
            self.assertEqual(case_input, deb822_file.convert_to_text(),
                             "Input of case " + c + " is round trip safe")
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
                self.assertEqual(list(repro_paragraph), list(deb822_paragraph),
                                 "Ensure keys are the same and in the correct order, case " + c)
                # Use the key from Deb822 as it is compatible with the round safe version
                # (the reverse is not true typing wise)
                for k, ev in deb822_paragraph.items():
                    av = repro_paragraph[k]
                    self.assertEqual(av, ev, "Ensure value for " + k + " is the same, case " + c)

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
        self.assertEqual("foo", source_paragraph['Source'])
        self.assertEqual("1.2.3", source_paragraph['Standards-Version'])
        self.assertEqual("no", source_paragraph['Rules-Requires-Root'])

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

        self.assertEqual(expected, deb822_file.convert_to_text(),
                         "Mutation should have worked while preserving comments")

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

        self.assertEqual(expected, deb822_file.convert_to_text(),
                         "Mutation should have worked while but discarded comments")

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
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))

        with self.assertRaises(ValueError):
            # But the parser should raise an error if explicitly requested
            parse_deb822_file(original.splitlines(keepends=True),
                              accept_files_with_error_tokens=True,
                              accept_files_with_duplicated_fields=False,
                              )

        source_paragraph = next(iter(deb822_file))
        as_dict = source_paragraph.configured_view(auto_resolve_ambiguous_fields=False)
        # Non-ambiguous fields are fine
        self.assertEqual("foo", as_dict['Source'])
        self.assertEqual("1.2.3", as_dict['Standards-Version'])
        with self.assertRaises(AmbiguousDeb822FieldKeyError):
            v = as_dict['Rules-Requires-Root']
        as_dict_auto_resolve = source_paragraph.configured_view(auto_resolve_ambiguous_fields=True)
        self.assertEqual("foo", as_dict_auto_resolve['Source'])
        self.assertEqual("1.2.3", as_dict_auto_resolve['Standards-Version'])
        # Auto-resolution always takes the first field value
        self.assertEqual("no", as_dict_auto_resolve['Rules-Requires-Root'])
        # It should be possible to "fix" the duplicate field by setting the field explicitly
        as_dict_auto_resolve['Rules-Requires-Root'] = as_dict_auto_resolve['Rules-Requires-Root']

        expected_fixed = original.replace('Rules-Requires-Root: binary-targets\n', '')
        self.assertEqual(expected_fixed, deb822_file.convert_to_text(),
                         "Fixed version should only have one Rules-Requires-Root field")

        # As an alternative, we can also fix the problem if we discard comments
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))
        as_dict_discard_comments = source_paragraph.configured_view(
            preserve_field_comments_on_field_updates=False,
            auto_resolve_ambiguous_fields=False,
        )
        # First, ensure the reset succeeded
        with self.assertRaises(AmbiguousDeb822FieldKeyError):
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
        self.assertEqual(expected, deb822_file.convert_to_text(),
                         "Fixed version should only have one Rules-Requires-Root field")

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

        self.assertEqual(sorted_nodups, deb822_file_nodups.convert_to_text(),
                         "Sorting without duplicated fields work")
        deb822_file_with_dups = parse_deb822_file(original_with_dups.splitlines(keepends=True))

        for paragraph in deb822_file_with_dups:
            paragraph.sort_fields(key=key_func)

        self.assertEqual(sorted_with_dups, deb822_file_with_dups.convert_to_text(),
                         "Sorting with duplicated fields work")

    def test_interpretation(self):
        # type: () -> None

        original = textwrap.dedent('''\
        Package: foo
        Architecture: amd64  i386
        # Also on kfreebsd
          kfreebsd-amd64  kfreebsd-i386
        # With leading comma :)
        Some-Comma-List: , a,  b , c
        ''')
        deb822_file = parse_deb822_file(original.splitlines(keepends=True))
        source_paragraph = next(iter(deb822_file))

        @contextlib.contextmanager
        def _field_mutation_test(
                kvpair,           # type: Deb822KeyValuePairElement
                interpretation,   # type: Interpretation[Deb822ParsedTokenList[VT, ST]]
                expected_output,  # type: str
                ):
            # type: (...) -> Iterator[Deb822ParsedTokenList[VT, ST]]
            original_value_element = kvpair.value_element
            with kvpair.interpret_as(interpretation) as value_list:
                yield value_list

            # We always match without the field comment to keep things simple.
            actual = kvpair.field_name + ":" + kvpair.value_element.convert_to_text()
            try:
                self.assertEqual(expected_output, actual)
            except AssertionError:
                logging.info(" -- Debugging aid - START of AST for generated value --")
                print_ast(kvpair)
                logging.info(" -- Debugging aid - END of AST for generated value --")
                raise
            # Reset of value
            kvpair.value_element = original_value_element
            self.assertEqual(original, deb822_file.convert_to_text())

        arch_kvpair = source_paragraph.get_kvpair_element('Architecture')
        comma_list_kvpair = source_paragraph.get_kvpair_element('Some-Comma-List')
        assert arch_kvpair is not None and comma_list_kvpair is not None
        archs = arch_kvpair.interpret_as(LIST_SPACE_SEPARATED_INTERPRETATION)
        comma_list_misread = comma_list_kvpair.interpret_as(
            LIST_SPACE_SEPARATED_INTERPRETATION
        )
        self.assertEqual(['amd64', 'i386', 'kfreebsd-amd64', 'kfreebsd-i386'],
                         list(archs))
        self.assertEqual([',', 'a,', 'b', ',', 'c'],
                         list(comma_list_misread))

        comma_list_correctly_read = comma_list_kvpair.interpret_as(
            LIST_COMMA_SEPARATED_INTERPRETATION
        )

        self.assertEqual(['a', 'b', 'c'], list(comma_list_correctly_read))

        # Interpretation must not change the content
        self.assertEqual(original, deb822_file.convert_to_text())

        # But we can choose to modify the content
        expected_result = 'Some-Comma-List: , a,  b , c, d,e,\n'
        with _field_mutation_test(comma_list_kvpair,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  expected_result) as comma_list:
            comma_list.no_reformatting_when_finished()
            comma_list.append('d')
            # We can also omit the space after a separator
            comma_list.append_separator(space_after_separator=False)
            comma_list.append('e')
            comma_list.append_separator(space_after_separator=False)

        # ... and this time we reformat to make it look nicer
        expected_result = textwrap.dedent('''\
            Some-Comma-List: a,
                             c,
            # Something important about "d"
            #
            # ... that spans multiple lines    ¶
                             d,
        ''').replace('¶', '')
        with _field_mutation_test(comma_list_kvpair,
                                  LIST_COMMA_SEPARATED_INTERPRETATION,
                                  expected_result) as comma_list:
            comma_list.reformat_when_finished()
            comma_list.append_comment('Something important about "d"')
            comma_list.append_comment('')
            # We can control spacing by explicitly using "#" and "\n"
            comma_list.append_comment('# ... that spans multiple lines    \n')
            comma_list.append('d')
            comma_list.remove('b')

        # If we choose the wrong type of interpretation, the result should still be a valid Deb822 file
        # (even if the contents gets a bit wrong).
        expected_result = textwrap.dedent('''\
             Some-Comma-List: ,
                              a,
                              b
                              ,
                              c
                              d
             ''')
        with _field_mutation_test(comma_list_kvpair,
                                  LIST_SPACE_SEPARATED_INTERPRETATION,
                                  expected_result) as comma_list_misread:
            comma_list_misread.reformat_when_finished()
            comma_list_misread.append('d')

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

            def _key_func(value):
                # type: (Deb822Token) -> Any
                v = value.text
                if '-' in v:
                    ov = order.get(v.split('-')[0])
                    if ov is None:
                        ov = 0
                else:
                    ov = 0
                return ov, v

            arch_list.sort(key=_key_func)
