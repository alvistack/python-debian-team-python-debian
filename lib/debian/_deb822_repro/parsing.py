# -*- coding: utf-8 -*- vim: fileencoding=utf-8 :

""" Round-trip safe dictionary-like interfaces to RFC822-like files

This module is a round-trip safe API for working with RFC822-like Debian data
formats. It is primarily aimed files managed by humans, like debian/control.
While it is be able to process any Deb822 file, you might find the debian.deb822
module better suited for larger files such as the `Packages` and `Sources`
from the Debian archive due to reasons explained below.

Being round-trip safe means that this module will faithfully preserve the original
formatting including whitespace and comments from the input where not modified.
A concrete example example::

    >>> from debian._deb822_repro import parse_deb822_file
    >>> example_deb822_paragraph = '''
    ... Package: foo
    ... # Field comment (because it becomes just before a field)
    ... Section: main/devel
    ... Depends: libfoo,
    ... # Inline comment (associated with the next line)
    ...          libbar,
    ... '''
    >>> deb822_file = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
    >>> paragraph = next(iter(deb822_file))
    >>> paragraph['Section'] = 'devel'
    >>> output = deb822_file.convert_to_text()
    >>> output == example_deb822_paragraph.replace('Section: main/devel', 'Section: devel')
    True

This makes it particularly good for automated changes/corrections to files (partly)
maintained by humans.

Compared to debian.deb822
-------------------------

The round-trip safe API is primarily useful when your program is editing files
and the file in question is (likely) to be hand-edited or formated directly by
human maintainers.  This includes files like debian/control and the
debian/copyright using the "DEP-5" format.

The round-trip safe API also supports parsing and working with invalid files.
This enables programs to work on the file in cases where the file was a left
with an error in an attempt to correct it (or ignore it).

On the flip side, the debian.deb822 module generally uses less memory than the
round trip safe API. In some cases, it will also have faster data structures
because its internal data structures are simpler. Accordingly, when you are doing
read-only work or/and working with large files a la the Packages or Sources
files from the Debian archive, then the round-trip safe API either provides no
advantages or its trade-offs might show up in performance statistics.

The memory and runtime performance difference should generally be constant for
valid files but not necessarily a small one.  For invalid files, some operations
can degrade in runtime performance in particular cases (memory performance for
invalid files are comparable to that of valid files).

Converting from debian.deb822
=============================

The following is a short example for how to migrate from debian.deb822 to
the round-trip safe API. Given the following source text::

    >>> dctrl_input = b'''
    ... Source: foo
    ... Build-Depends: debhelper-compat (= 13)
    ...
    ... Package: bar
    ... Architecture: any
    ... Depends: ${misc:Depends},
    ...          ${shlibs:Depends},
    ... Description: provides some exciting feature
    ...  yada yada yada
    ...  .
    ...  more deskription with a misspelling
    ... '''.lstrip()  # To remove the leading newline
    >>> # A few definitions to emulate file I/O (would be different in the program)
    >>> import contextlib
    >>> @contextlib.contextmanager
    ... def open_input():
    ...     yield dctrl_input.splitlines(keepends=True)
    >>> def open_output():
    ...    return open('/dev/null', 'wb')

With debian.deb822, your code might look like this::

    >>> from debian.deb822 import Deb822
    >>> with open_input() as in_fd, open_output() as out_fd:
    ...     for paragraph in Deb822.iter_paragraphs(in_fd):
    ...         if 'Description' not in paragraph:
    ...             continue
    ...         description = paragraph['Description']
    ...         # Fix typo
    ...         paragraph['Description'] = description.replace('deskription', 'description')
    ...         paragraph.dump(out_fd)

With the round-trip safe API, the rewrite would look like this::

    >>> from debian._deb822_repro import parse_deb822_file
    >>> with open_input() as in_fd, open_output() as out_fd:
    ...     parsed_file = parse_deb822_file(in_fd)
    ...     for paragraph in parsed_file:
    ...         if 'Description' not in paragraph:
    ...             continue
    ...         description = paragraph['Description']
    ...         # Fix typo
    ...         paragraph['Description'] = description.replace('deskription', 'description')
    ...     parsed_file.dump(out_fd)

Key changes are:

 1. Imports are different.
 2. Deb822.iter_paragraphs is replaced by parse_deb822_file and a reference to
    its return value is kept for later.
 3. Instead of dumping paragraphs one by one, the return value from
    parse_deb822_file is dumped at the end.

Note that the round trip safe API does not accept all the same parameters as the
debian.deb822 module does.  Often this is because the feature is not relevant for
the round-trip safe API (e.g., python-apt cannot be used as it discard comments)
or is obsolete in the debian.deb822 module and therefore omitted.

For list based fields, you may want to have a look at the
Deb822ParagraphElement.as_interpreted_dict_view method.

Stability of this API
---------------------

The API is subject to change based on feedback from early adoptors and beta
testers.  That said, the code for valid files is unlikely to change in
a backwards incompatible way.

Things that might change in an incompatible way include:
 * Whether invalid files are accepted (parsed without errors) by default.
   (currently they are)
 * How invalid files are parsed.  As an example, currently a syntax error acts
   as a paragraph separator. Whether it should is open to debate.

"""

import collections.abc
import contextlib
import operator
import re
import sys
import textwrap
import weakref
from abc import ABC
from types import TracebackType
from weakref import ReferenceType

try:
    from typing import (
        Iterable, Iterator, List, Union, Dict, Optional, Callable, Any, Generic, Type, Tuple, IO,
        cast,
    )
    # for some reason, pylint does not see that Commentish is used in typing
    from debian._deb822_repro.types import (  # pylint: disable=unused-import
        T, ST, VT, TE,
        ParagraphKey, TokenOrElement, Commentish, ParagraphKeyBase,
    )
except ImportError:
    cast = lambda t, v: v

from debian.deb822 import _strI, OrderedSet

from debian._deb822_repro.types import AmbiguousDeb822FieldKeyError
from debian._deb822_repro.tokens import (
    Deb822Token, Deb822ValueToken, Deb822SemanticallySignificantWhiteSpace,
    Deb822SpaceSeparatorToken, Deb822CommentToken, Deb822WhitespaceToken,
    Deb822ValueContinuationToken, Deb822NewlineAfterValueToken, Deb822CommaToken,
    Deb822FieldNameToken, Deb822FieldSeparatorToken, Deb822ErrorToken,
    _RE_WHITESPACE_LINE, tokenize_deb822_file,
)
from debian._deb822_repro._util import (resolve_ref, LinkedList, LinkedListNode,
                                        combine_into_replacement, BufferingIterator,
                                        flatten_with_len_check,
)

_RE_WHITESPACE = re.compile(r'\s+')
# Consume whitespace and a single word.
_RE_WHITESPACE_SEPARATED_WORD_LIST = re.compile(r'''
    (?P<space_before>\s*)                # Consume any whitespace before the word
                                         # The space only occurs in practise if the line starts
                                         # with space.

                                         # Optionally consume a word (needed to handle the case
                                         # when there are no words left and someone applies this
                                         # pattern to the remaining text). This is mostly here as
                                         # a fail-safe.

    (?P<word>\S+)                        # Consume the word (if present)
    (?P<trailing_whitespace>\s*)         # Consume trailing whitespace
''', re.VERBOSE)
_RE_COMMA_SEPARATED_WORD_LIST = re.compile(r'''
    # This regex is slightly complicated by the fact that it should work with
    # finditer and comsume the entire value.
    #
    # To do this, we structure the regex so it always starts on a comma (except
    # for the first iteration, where we permit the absence of a comma)

    (?:                                      # Optional space followed by a mandatory comma unless
                                             # it is the start of the "line" (in which case, we
                                             # allow the comma to be omitted)
        ^
        |
        (?:
            (?P<space_before_comma>\s*)      # This space only occurs in practise if the line
                                             # starts with space + comma.
            (?P<comma> ,)
        )
    )

    # From here it is "optional space, maybe a word and then optional space" again.  One reason why
    # all of it is optional is to gracefully cope with trailing commas.
    (?P<space_before_word>\s*)
    (?P<word> [^,\s] (?: [^,]*[^,\s])? )?    # "Words" can contain spaces for comma separated list.
                                             # But surrounding whitespace is ignored
    (?P<space_after_word>\s*)
''', re.VERBOSE)


class Deb822ParsedTokenList(Generic[VT, ST],
                            contextlib.AbstractContextManager['Deb822ParsedTokenList[VT, ST]']
                            ):

    def __init__(self,
                 kvpair_element,  # type: 'Deb822KeyValuePairElement'
                 interpreted_value_element,  # type: 'List[Deb822Token]'
                 vtype,  # type: Type[VT]
                 stype,  # type: Type[ST]
                 tokenizer,  # type: Callable[[str], Iterable['Deb822Token']]
                 default_separator_factory,  # type: Callable[[], ST]
                 ):
        # type: (...) -> None
        self._kvpair_element = kvpair_element
        self._token_list = LinkedList(interpreted_value_element)
        self._vtype = vtype
        self._stype = stype
        self._tokenizer = tokenizer
        self._default_separator_factory = default_separator_factory
        self._value_factory = _tokenizer_to_value_factory(tokenizer, vtype)
        self._format_preserve_original_formatting = True
        self._format_one_value_per_line = False
        self._format_with_leading_whitespace_matching_field_length = False
        self._format_trailing_separator_after_last_element = False
        self._changed = False
        assert self._token_list
        last_token = self._token_list.tail

        if last_token is not None and isinstance(last_token, Deb822NewlineAfterValueToken):
            # We always remove the last newline (if present), because then
            # adding values will happen after the last value rather than on
            # a new line by default.
            #
            # On write, we always ensure the value ends on a newline (even
            # if it did not before).  This is simpler and should be a
            # non-issue in practise.
            self._token_list.pop()

    def __iter__(self):
        # type: () -> Iterator[str]
        yield from (v.convert_to_text() for v in self.value_parts)

    def __bool__(self):
        # type: () -> bool
        return next(iter(self), None) is not None

    def __exit__(self,
                 exc_type,  # type: Optional[Type[BaseException]]
                 exc_val,  # type: Optional[BaseException]
                 exc_tb,  # type: Optional[TracebackType]
                 ):
        # type: (...) -> Optional[bool]
        if exc_type is None and self._changed:
            self._update_field()
        return super().__exit__(exc_type, exc_val, exc_tb)

    @property
    def value_parts(self):
        # type: () -> Iterator[TE]
        yield from (v for v in self._token_list if isinstance(v, self._vtype))

    def append_separator(self, space_after_separator=True):
        # type: (bool) -> None

        separator_token = self._default_separator_factory()
        if separator_token.is_whitespace:
            space_after_separator = False

        self._changed = True
        self._append_continuation_line_token_if_necessary()
        self._token_list.append(separator_token)

        if space_after_separator and not separator_token.is_whitespace:
            self._token_list.append(Deb822WhitespaceToken(' '))

    def replace(self, orig_value, new_value):
        # type: (str, str) -> None
        """Replace the first instance of a value with another"""
        for node in self._token_list.iter_nodes():
            if node.value.text == orig_value:
                node.value = self._value_factory(new_value)
                self._changed = True
                break
        else:
            raise ValueError("list.replace(x, y): x not in list")

    def remove(self, value):
        # type: (str) -> None
        vtype = self._vtype
        for node in self._token_list.iter_nodes():
            if node.value.text == value and isinstance(node.value, vtype):
                node_to_remove = node
                break
        else:
            raise ValueError("list.remove(x): x not in list")

        self._changed = True

        # We naively want to remove the node and every thing to the left of it
        # until the previous value.  That is the basic idea for now (ignoring
        # special-cases for now).
        #
        # Example:
        #
        # """
        # Multiline-Keywords: bar[
        # # Comment about foo
        #                     foo]
        #                     baz
        # Keywords: bar[ foo] baz
        # Comma-List: bar[, foo], baz,
        # Multiline-Comma-List: bar[,
        # # Comment about foo
        #                       foo],
        #                       baz,
        # """
        #
        # Assuming we want to remove "foo" for the lists, the []-markers
        # show what we aim to remove.  This has the nice side-effect of
        # preserving whether nor not the value has a trailing separator.
        # Note that we do *not* attempt to repair missing separators but
        # it may fix duplicated separators by "accident".
        #
        # Now, there are two special cases to be aware of, where this approach
        # has short comings:
        #
        # 1) If foo is the only value (in which case, "delete everything"
        #    is the only option).
        # 2) If foo is the first value
        # 3) If foo is not the only value on the line and we see a comment
        #    inside the deletion range.
        #
        # For 2) + 3), we attempt to flip and range to delete and every
        # thing after it (up to but exclusion "baz") instead.  This
        # definitely fixes 3), but 2) has yet another corner case, namely:
        #
        # """
        # Multiline-Comma-List: foo,
        # # Remark about bar
        #                       bar,
        # Another-Case: foo
        # # Remark, also we use leading separator
        #             , bar
        # """
        #
        # The options include:
        #
        #  A) Discard the comment - brain-dead simple
        #  B) Hoist the comment up to a field comment, but then what if the
        #     field already has a comment?
        #  C) Clear the first value line leaving just the newline and
        #     replace the separator before "bar" (if present) with a space.
        #     (leaving you with the value of the form "\n# ...\n      bar")
        #

        first_value_on_lhs = None  # type: Optional[LinkedListNode[Deb822Token]]
        first_value_on_rhs = None  # type: Optional[LinkedListNode[Deb822Token]]
        comment_before_previous_value = False
        comment_before_next_value = False
        for past_node in node_to_remove.iter_previous(skip_current=True):
            past_token = past_node.value
            if past_token.is_comment:
                comment_before_previous_value = True
                continue
            if isinstance(past_token, vtype):
                first_value_on_lhs = past_node
                break

        for future_node in node_to_remove.iter_next(skip_current=True):
            future_token = future_node.value
            if future_token.is_comment:
                comment_before_next_value = True
                continue
            if isinstance(future_token, vtype):
                first_value_on_rhs = future_node
                break

        if first_value_on_rhs is None and first_value_on_lhs is None:
            # This was the last value, just remove everything.
            self._token_list.clear()
            return

        if first_value_on_lhs is not None and not comment_before_previous_value:
            # Delete left
            delete_lhs_of_node = True
        elif first_value_on_rhs is not None and not comment_before_next_value:
            # Delete right
            delete_lhs_of_node = False
        else:
            # There is a comment on either side (or no value on one and a
            # comment and the other). Keep it simple, we just delete to
            # one side (preferring deleting to left if possible).
            delete_lhs_of_node = first_value_on_lhs is not None

        if delete_lhs_of_node:
            first_remain_lhs = first_value_on_lhs
            first_remain_rhs = node_to_remove.next_node
        else:
            first_remain_lhs = node_to_remove.previous_node
            first_remain_rhs = first_value_on_rhs

        # Actual deletion - with some manual labour to update HEAD/TAIL of
        # the list in case we do a "delete everything left/right this node".
        if first_remain_lhs is None:
            self._token_list.head_node = first_remain_rhs
        if first_remain_rhs is None:
            self._token_list.tail_node = first_remain_lhs
        LinkedListNode.link_nodes(first_remain_lhs, first_remain_rhs)

    def append(self, value):
        # type: (str) -> None
        vt = self._value_factory(value)
        self.append_value(vt)

    def append_value(self, vt):
        # type: (VT) -> None
        value_parts = self._token_list
        if value_parts:
            needs_separator = False
            stype = self._stype
            vtype = self._vtype
            for t in reversed(value_parts):
                if isinstance(t, vtype):
                    needs_separator = True
                    break
                if isinstance(t, stype):
                    break

            if needs_separator:
                self.append_separator()
        else:
            # Looks nicer if there is a space before the very first value
            self._token_list.append(Deb822WhitespaceToken(' '))
        self._append_continuation_line_token_if_necessary()
        self._changed = True
        value_parts.append(vt)

    def _previous_is_newline(self):
        # type: () -> bool
        tail = self._token_list.tail
        return tail is not None and tail.text.endswith("\n")

    def append_newline(self):
        # type: () -> None
        if self._previous_is_newline():
            raise ValueError("Cannot add a newline after a token that ends on a newline")
        self._token_list.append(Deb822NewlineAfterValueToken())

    def append_comment(self, comment_text):
        # type: (str) -> None
        tail = self._token_list.tail
        if tail is None or not tail.text.endswith('\n'):
            self.append_newline()
        comment_token = Deb822CommentToken(_format_comment(comment_text))
        self._token_list.append(comment_token)

    def _append_continuation_line_token_if_necessary(self):
        # type: () -> None
        tail = self._token_list.tail
        if tail is not None and tail.text.endswith("\n"):
            self._token_list.append(Deb822ValueContinuationToken())

    def reformat_when_finished(self):
        # type: () -> None
        self._enable_reformatting()
        self._changed = True

    def _enable_reformatting(self):
        # type: () -> None
        self._format_one_value_per_line = True
        self._format_with_leading_whitespace_matching_field_length = True
        self._format_trailing_separator_after_last_element = True
        self._format_preserve_original_formatting = False

    def no_reformatting_when_finished(self):
        # type: () -> None
        self._format_one_value_per_line = False
        self._format_with_leading_whitespace_matching_field_length = False
        self._format_trailing_separator_after_last_element = False
        self._format_preserve_original_formatting = True

    def _generate_reformatted_field_content(self):
        # type: () -> str
        separator_token = self._default_separator_factory()
        space_after_newline = ' '
        separator_includes_newline = self._format_one_value_per_line
        if separator_token.is_whitespace:
            separator_as_text = ''
        else:
            separator_as_text = separator_token.text
        if separator_includes_newline:
            separator_with_space = separator_as_text + '\n '
            if self._format_with_leading_whitespace_matching_field_length:
                space_len = len(self._kvpair_element.field_name)
                # Plus 2 (one for the separator and one for the space after it)
                # This space already covers the mandatory space at the beginning
                # of a continuation line
                space_len += 2
                separator_with_space = separator_as_text + '\n'
                space_after_newline = ' ' * space_len
        else:
            separator_with_space = separator_as_text + ' '

        vtype = self._vtype
        token_iter = (t for t in self._token_list
                      if t.is_comment or isinstance(t, vtype)
                      )  # type: Iterator[Deb822Token]

        def _token_iter():
            # type: () -> Iterable[str]
            first_token = next(token_iter, None)  # type: Optional[Deb822Token]
            assert first_token is not None and isinstance(first_token, vtype)
            # Leading space after ":"
            yield ' '
            # Not sure why mypy concludes that first_token must be "<nothing>"
            # when it is clearly typed as a Deb822Token plus it would have
            # passed an "assert isinstance" check too.
            yield first_token.text  # type: ignore
            pending_separator = True
            ended_on_a_newline = False
            last_token = first_token  # type: Deb822Token
            for t in token_iter:
                if t.is_comment:
                    if pending_separator:
                        if separator_as_text:
                            yield separator_as_text
                    if not last_token.is_comment or not separator_includes_newline:
                        yield "\n"
                    yield t.text
                    pending_separator = False
                    ended_on_a_newline = True
                else:
                    if pending_separator:
                        yield separator_with_space
                        ended_on_a_newline = separator_includes_newline
                    if ended_on_a_newline:
                        yield space_after_newline
                    yield t.text
                    ended_on_a_newline = False
                    pending_separator = True
                last_token = t

            # We do not support values ending on a comment
            assert last_token is not None and not last_token.is_comment
            if self._format_trailing_separator_after_last_element and separator_as_text:
                yield separator_as_text
            yield '\n'

        return ''.join(_token_iter())

    def _generate_field_content(self):
        # type: () -> str
        return "".join(t.text for t in self._token_list)

    def _update_field(self):
        # type: () -> None
        kvpair_element = self._kvpair_element
        field_name = kvpair_element.field_name
        token_list = self._token_list
        tail = token_list.tail

        for t in token_list:
            if not t.is_comment and not t.is_whitespace:
                break
        else:
            raise ValueError("Field must have content (i.e. non-whitespace and non-comments)")

        assert tail is not None
        if tail.is_comment:
            raise ValueError("Fields must not end on a comment")
        if not tail.text.endswith("\n"):
            # Always end on a newline
            self.append_newline()

        if self._format_preserve_original_formatting:
            value_text = self._generate_field_content()
        else:
            value_text = self._generate_reformatted_field_content()
        text = ':'.join((field_name, value_text))
        new_content = text.splitlines(keepends=True)

        # As absurd as it might seem, it is easier to just use the parser to
        # construct the AST correctly
        deb822_file = parse_deb822_file(iter(new_content))
        error_token = deb822_file.find_first_error_element()
        if error_token:
            # _print_ast(deb822_file)
            raise ValueError("Syntax error in new field value for " + field_name)
        paragraph = next(iter(deb822_file))
        assert isinstance(paragraph, Deb822ValidParagraphElement)
        new_kvpair_element = paragraph.get_kvpair_element(field_name)
        assert new_kvpair_element is not None
        kvpair_element.value_element = new_kvpair_element.value_element
        self._changed = False

    def sort(self, *,
             key=None,  # type: Optional[Callable[[VT], Any]]
             reverse=False,  # type: bool
    ):
        # type: (...) -> None
        """Sort the elements (values) in this list.

        This method will sort the logical values of the list. It will
        attempt to preserve comments associated with a given value where
        possible.  Whether space and separators are preserved depends on
        the contents of the field as well as the formatting settings.

        Sorting (without reformatting) is likely to leave you with "awkward"
        whitespace. Therefore, you almost always want to apply reformatting
        such as the reformat_when_finished() method.


        """
        comment_start_node = None
        vtype = self._vtype
        stype = self._stype

        def key_func(x):
            # type: (Tuple[VT, List[Deb822Token]]) -> Any
            if key:
                return key(x[0])
            return x[0].convert_to_text()

        parts = []

        for node in self._token_list.iter_nodes():
            value = node.value
            if value.is_comment:
                if comment_start_node is None:
                    comment_start_node = node
                continue

            if isinstance(value, vtype):
                comments = []
                if comment_start_node is not None:
                    for keep_node in comment_start_node.iter_next(skip_current=False):
                        if keep_node is node:
                            break
                        comments.append(keep_node.value)
                parts.append((value, comments))
                comment_start_node = None

        parts.sort(key=key_func, reverse=reverse)

        self._changed = True
        self._token_list.clear()
        first_value = True

        separator_is_space = self._default_separator_factory().is_whitespace

        for value, comments in parts:
            if first_value:
                first_value = False
                if comments:
                    # While unlikely, there could be a separator between the comments.
                    # It would be in the way and we remove it.
                    comments = [x for x in comments if not isinstance(x, stype)]
                    # Comments cannot start the field, so inject a newline to
                    # work around that
                    self.append_newline()
            else:
                if not separator_is_space and not any(isinstance(x, stype) for x in comments):
                    # While unlikely, you can hide a comma between two comments and expect
                    # us to preserve it.  However, the more common case is that the separator
                    # appeared before the comments and was thus omitted (leaving us to re-add
                    # it here).
                    self.append_separator(space_after_separator=False)
                if comments or self._format_one_value_per_line:
                    self.append_newline()
                else:
                    self._token_list.append(Deb822WhitespaceToken(' '))

            self._token_list.extend(comments)
            self.append_value(value)


class Interpretation(Generic[T]):

    def interpret(self, kvpair_element):
        # type: (Deb822KeyValuePairElement) -> T
        raise NotImplementedError  # pragma: no cover


class LineByLineBasedInterpretation(Interpretation[T]):

    def __init__(self,
                 tokenizer):
        # type: (Callable[[str], Iterable['Deb822Token']]) -> None
        super().__init__()
        self._tokenizer = tokenizer

    def _high_level_interpretation(self, kvpair_element, token_list):
        # type: (Deb822KeyValuePairElement, List['Deb822Token']) -> T
        raise NotImplementedError  # pragma: no cover

    def interpret(self, kvpair_element):
        # type: (Deb822KeyValuePairElement) -> T
        code = self._tokenizer
        token_list = []  # type: List['Deb822Token']
        for vl in kvpair_element.value_element.value_lines:
            content_text = vl.convert_content_to_text()

            value_parts = list(flatten_with_len_check(content_text,
                                                      code(content_text)
                                                      ))
            if vl.comment_element:
                token_list.extend(vl.comment_element.iter_tokens())
            if vl.continuation_line_token:
                token_list.append(vl.continuation_line_token)
            token_list.extend(value_parts)
            if vl.newline_token:
                token_list.append(vl.newline_token)

        return self._high_level_interpretation(kvpair_element, token_list)


def _tokenizer_to_value_factory(tokenizer,  # type: Callable[[str], Iterable['Deb822Token']]
                                vtype,  # type: Type[VT]
                                ):
    # type: (...) -> Callable[[str], VT]
    def _value_factory(v):
        # type: (str) -> VT
        if v == '':
            raise ValueError("The empty string is not a value")
        token_iter = iter(tokenizer(v))
        t1 = next(token_iter, None)  # type: Optional[Union[Deb822Token, VT]]
        t2 = next(token_iter, None)
        assert t1 is not None, 'Bad tokenizer - it returned None (or no tokens) for "' + v + '"'
        if t2 is not None:
            msg = textwrap.dedent("""\
            The input "{v}" should have been exactly one token, but the tokenizer provided at
             least two.  This can happen with unnecessary leading/trailing whitespace
             or including commas the value for a comma list.
            """).format(v=v)
            raise ValueError(msg)
        if not isinstance(t1, vtype):
            msg = 'The input "{v}" should have produced a token of type {vtype_name}, but' \
                  ' instead it produced {t1}'
            raise ValueError(msg.format(v=v, vtype_name=vtype.__name__, t1=t1))

        assert len(t1.text) == len(v), "Bad tokenizer - the token did not cover the input text" \
                                       " exactly ({t1_len} != {v_len}".format(
            t1_len=len(t1.text), v_len=len(v)
        )
        return t1

    return _value_factory


class ListInterpretation(LineByLineBasedInterpretation[Deb822ParsedTokenList[VT, ST]]):

    def __init__(self,
                 tokenizer,  # type: Callable[[str], Iterable['Deb822Token']]
                 vtype,  # type: Type[VT]
                 stype,  # type: Type[ST]
                 default_separator_factory,  # type: Callable[[], ST]
                 ):
        # type: (...) -> None
        super().__init__(tokenizer)
        self._vtype = vtype
        self._stype = stype
        self._default_separator_factory = default_separator_factory

    def _high_level_interpretation(self,
                                   kvpair_element,  # type: Deb822KeyValuePairElement
                                   token_list,  # type: List['Deb822Token']
                                   ):
        # type: (...) -> Deb822ParsedTokenList[VT, ST]
        return Deb822ParsedTokenList(
            kvpair_element,
            token_list,
            self._vtype,
            self._stype,
            self._tokenizer,
            self._default_separator_factory,
        )


def _whitespace_separated_list_of_tokens(v):
    # type: (str) -> Iterable[Deb822Token]
    assert not _RE_WHITESPACE_LINE.match(v)
    for match in _RE_WHITESPACE_SEPARATED_WORD_LIST.finditer(v):
        space_before, word, space_after = match.groups()
        if space_before:
            yield Deb822SpaceSeparatorToken(sys.intern(space_before))
        yield Deb822ValueToken(word)
        if space_after:
            yield Deb822SpaceSeparatorToken(sys.intern(space_after))


def _comma_separated_list_of_tokens(v):
    # type: (str) -> Iterable[Deb822Token]
    assert not _RE_WHITESPACE_LINE.match(v)
    for match in _RE_COMMA_SEPARATED_WORD_LIST.finditer(v):
        space_before_comma, comma, space_before_word, word, space_after_word = match.groups()
        if space_before_comma:
            yield Deb822WhitespaceToken(sys.intern(space_before_comma))
        if comma:
            yield Deb822CommaToken()
        if space_before_word:
            yield Deb822WhitespaceToken(sys.intern(space_before_word))
        if word:
            yield Deb822ValueToken(word)
        if space_after_word:
            yield Deb822WhitespaceToken(sys.intern(space_after_word))


class Deb822Element:
    """Composite elements (consists of 1 or more tokens)"""

    __slots__ = ('_parent_element', '__weakref__')

    def __init__(self):
        # type: () -> None
        self._parent_element = None  # type: Optional[ReferenceType['Deb822Element']]

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        raise NotImplementedError  # pragma: no cover

    def iter_parts_of_type(self, only_element_or_token_type):
        # type: (Type[TE]) -> Iterable[TE]
        for part in self.iter_parts():
            if isinstance(part, only_element_or_token_type):
                yield part

    def iter_tokens(self):
        # type: () -> Iterable[Deb822Token]
        for part in self.iter_parts():
            if isinstance(part, Deb822Element):
                yield from part.iter_tokens()
            else:
                yield part

    def iter_recurse(self, *,
                     only_element_or_token_type=None,  # type: Optional[Type[TE]]
                     ):
        # type: (...) -> Iterable[TE]
        for part in self.iter_parts():
            if only_element_or_token_type is None or isinstance(part, only_element_or_token_type):
                yield cast('TE', part)
            if isinstance(part, Deb822Element):
                yield from part.iter_recurse(only_element_or_token_type=only_element_or_token_type)

    @property
    def parent_element(self):
        # type: () -> Optional[Deb822Element]
        return resolve_ref(self._parent_element)

    @parent_element.setter
    def parent_element(self, new_parent):
        # type: (Optional[Deb822Element]) -> None
        self._parent_element = weakref.ref(new_parent) if new_parent is not None else None

    def _init_parent_of_parts(self):
        # type: () -> None
        for part in self.iter_parts():
            part.parent_element = self

    # Deliberately not a "text" property, to signal that it is not necessary cheap.
    def convert_to_text(self):
        # type: () -> str
        return "".join(t.text for t in self.iter_tokens())

    def clear_parent_if_parent(self, parent):
        # type: (Deb822Element) -> None
        if parent is self.parent_element:
            self._parent_element = None


class Deb822ErrorElement(Deb822Element):
    """Element representing elements or tokens that are out of place

    Commonly, it will just be instances of Deb822ErrorToken, but it can be other
    things.  As an example if a parser discovers out of order elements/tokens,
    it can bundle them in a Deb822ErrorElement to signal that the sequence of
    elements/tokens are invalid (even if the tokens themselves are valid).
    """

    __slots__ = ('_parts',)

    def __init__(self, parts):
        # type: (List[TokenOrElement]) -> None
        super().__init__()
        self._parts = parts
        self._init_parent_of_parts()

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        yield from self._parts


class Deb822ValueLineElement(Deb822Element):
    """Consists of one "line" of a value"""

    __slots__ = ('_comment_element', '_continuation_line_token', '_leading_whitespace_token',
                 '_value_tokens', '_trailing_whitespace_token', '_newline_token')

    def __init__(self,
                 comment_element,  # type: Optional[Deb822CommentElement]
                 continuation_line_token,  # type: Optional[Deb822ValueContinuationToken]
                 leading_whitespace_token,  # type: Optional[Deb822WhitespaceToken]
                 value_parts,  # type: List[TokenOrElement]
                 trailing_whitespace_token,  # type: Optional[Deb822WhitespaceToken]
                 # only optional if it is the last line of the file and the file does not
                 # end with a newline.
                 newline_token,  # type: Optional[Deb822WhitespaceToken]
                 ):
        # type: (...) -> None
        super().__init__()
        if comment_element is not None and continuation_line_token is None:
            raise ValueError("Only continuation lines can have comments")
        self._comment_element = comment_element  # type: Optional[Deb822CommentElement]
        self._continuation_line_token = continuation_line_token
        self._leading_whitespace_token = \
            leading_whitespace_token  # type: Optional[Deb822WhitespaceToken]
        self._value_tokens = value_parts  # type: List[TokenOrElement]
        self._trailing_whitespace_token = trailing_whitespace_token
        self._newline_token = newline_token  # type: Optional[Deb822WhitespaceToken]
        self._init_parent_of_parts()

    @property
    def comment_element(self):
        # type: () -> Optional[Deb822CommentElement]
        return self._comment_element

    @property
    def continuation_line_token(self):
        # type: () -> Optional[Deb822ValueContinuationToken]
        return self._continuation_line_token

    @property
    def newline_token(self):
        # type: () -> Optional[Deb822WhitespaceToken]
        return self._newline_token

    def add_newline_if_missing(self):
        # type: () -> None
        if self._newline_token is None:
            self._newline_token = Deb822NewlineAfterValueToken()

    def _iter_content_parts(self):
        # type: () -> Iterable[TokenOrElement]
        if self._leading_whitespace_token:
            yield self._leading_whitespace_token
        yield from self._value_tokens
        if self._trailing_whitespace_token:
            yield self._trailing_whitespace_token

    def _iter_content_tokens(self):
        # type: () -> Iterable[Deb822Token]
        for part in self._iter_content_parts():
            if isinstance(part, Deb822Element):
                yield from part.iter_tokens()
            else:
                yield part

    def convert_content_to_text(self):
        # type: () -> str
        if len(self._value_tokens) == 1 \
                and not self._leading_whitespace_token \
                and not self._trailing_whitespace_token \
                and isinstance(self._value_tokens[0], Deb822Token):
            # By default, we get a single value spanning the entire line
            # (minus continuation line and newline but we are supposed to
            # exclude those)
            return self._value_tokens[0].text

        return "".join(t.text for t in self._iter_content_tokens())

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        if self._comment_element:
            yield self._comment_element
        if self._continuation_line_token:
            yield self._continuation_line_token
        yield from self._iter_content_parts()
        if self._newline_token:
            yield self._newline_token


class Deb822ValueElement(Deb822Element):
    __slots__ = ('_value_entry_elements',)

    def __init__(self, value_entry_elements):
        # type: (List[Deb822ValueLineElement]) -> None
        super().__init__()
        self._value_entry_elements = value_entry_elements  # type: List[Deb822ValueLineElement]
        self._init_parent_of_parts()

    @property
    def value_lines(self):
        # type: () -> List[Deb822ValueLineElement]
        """Read-only list of value entries"""
        return self._value_entry_elements

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        yield from self._value_entry_elements

    def add_final_newline_if_missing(self):
        # type: () -> None
        if self._value_entry_elements:
            self._value_entry_elements[-1].add_newline_if_missing()


class Deb822CommentElement(Deb822Element):
    __slots__ = ('_comment_tokens',)

    def __init__(self, comment_tokens):
        # type: (List[Deb822CommentToken]) -> None
        super().__init__()
        self._comment_tokens = comment_tokens  # type: List[Deb822CommentToken]
        if not comment_tokens:  # pragma: no cover
            raise ValueError("Comment elements must have at least one comment token")
        self._init_parent_of_parts()

    def __len__(self):
        # type: () -> int
        return len(self._comment_tokens)

    def __getitem__(self, item):
        # type: (int) -> Deb822CommentToken
        return self._comment_tokens[item]

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        yield from self._comment_tokens


class Deb822KeyValuePairElement(Deb822Element):
    __slots__ = ('_comment_element', '_field_token', '_separator_token', '_value_element')

    def __init__(self,
                 comment_element,  # type: Optional[Deb822CommentElement]
                 field_token,  # type: Deb822FieldNameToken
                 separator_token,  # type: Deb822FieldSeparatorToken
                 value_element,  # type: Deb822ValueElement
                 ):
        # type: (...) -> None
        super().__init__()
        self._comment_element = comment_element  # type: Optional[Deb822CommentElement]
        self._field_token = field_token  # type: Deb822FieldNameToken
        self._separator_token = separator_token  # type: Deb822FieldSeparatorToken
        self._value_element = value_element  # type: Deb822ValueElement
        self._init_parent_of_parts()

    @property
    def field_name(self):
        # type: () -> _strI
        return self.field_token.text

    @property
    def field_token(self):
        # type: () -> Deb822FieldNameToken
        return self._field_token

    @property
    def value_element(self):
        # type: () -> Deb822ValueElement
        return self._value_element

    @value_element.setter
    def value_element(self, new_value):
        # type: (Deb822ValueElement) -> None
        self._value_element.clear_parent_if_parent(self)
        self._value_element = new_value
        new_value.parent_element = self

    def interpret_as(self, interpreter):
        # type: (Interpretation[T]) -> T
        return interpreter.interpret(self)

    @property
    def comment_element(self):
        # type: () -> Optional[Deb822CommentElement]
        return self._comment_element

    @comment_element.setter
    def comment_element(self, value):
        # type: (Optional[Deb822CommentElement]) -> None
        if value is not None:
            if not value[-1].text.endswith("\n"):
                raise ValueError("Field comments must end with a newline")
        if self._comment_element:
            self._comment_element.clear_parent_if_parent(self)
        if value is not None:
            value.parent_element = self
        self._comment_element = value

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        if self._comment_element:
            yield self._comment_element
        yield self._field_token
        yield self._separator_token
        yield self._value_element


def _format_comment(c):
    # type: (str) -> str
    if c == '':
        # Special-case: Empty strings are mapped to an empty comment line
        return "#\n"
    if '\n' in c[:-1]:
        raise ValueError("Comment lines must not have embedded newlines")
    if not c.endswith('\n'):
        c = c.rstrip() + "\n"
    if not c.startswith("#"):
        c = "# " + c.lstrip()
    return c


def _unpack_key(item,  # type: ParagraphKey
                resolve_field_name=False,  # type: bool
                raise_if_indexed=False,  # type: bool
                ):
    # type: (...) -> Tuple[ParagraphKeyBase, Optional[int]]
    index = None  # type: Optional[int]
    key = None  # type: Optional[ParagraphKeyBase]
    if isinstance(item, tuple):
        key, index = item
        if raise_if_indexed:
            # Fudge "(key, 0)" into a "key" callers to defensively support
            # both paragraph styles with the same key.
            if index != 0:
                msg = 'Cannot resolve key "{key}" with index {index}. The key is not indexed'
                raise KeyError(msg.format(key=key, index=index))
            index = None
        if resolve_field_name:
            key = _strI(key)
    else:
        key = item
        index = None
        if resolve_field_name:
            if isinstance(key, Deb822FieldNameToken):
                key = key.text
            else:
                key = _strI(key)
    return key, index


def _convert_value_lines_to_lines(value_lines,  # type: Iterable[Deb822ValueLineElement]
                                  strip_comments,  # type: bool
                                  ):
    # type: (...) -> Iterable[str]
    if not strip_comments:
        yield from (v.convert_to_text() for v in value_lines)
    else:
        for element in value_lines:
            yield ''.join(x.text for x in element.iter_tokens()
                          if not x.is_comment)


# Deb822ParagraphElement uses this Mixin (by having `_paragraph` return self).
# Therefore the Mixin needs to call the "proper" methods on the paragraph to
# avoid doing infinite recursion.
class AutoResolvingMixin(Generic[T], collections.abc.Mapping[ParagraphKey, T]):

    @property
    def _auto_resolve_ambiguous_fields(self):
        # type: () -> bool
        return True

    @property
    def _paragraph(self):
        # type: () -> Deb822ParagraphElement
        raise NotImplementedError  # pragma: no cover

    def __len__(self):
        # type: () -> int
        return self._paragraph.kvpair_count

    def __contains__(self, item):
        # type: (object) -> bool
        return self._paragraph.contains_kvpair_element(item)

    def __iter__(self):
        # type: () -> Iterator[ParagraphKey]
        return iter(self._paragraph.iter_keys())

    def __getitem__(self, item):
        # type: (ParagraphKey) -> T
        if self._auto_resolve_ambiguous_fields and isinstance(item, str):
            v = self._paragraph.get_kvpair_element((item, 0))
        else:
            v = self._paragraph.get_kvpair_element(item)
        assert v is not None
        return self._interpret_value(item, v)

    def __delitem__(self, item):
        # type: (ParagraphKey) -> None
        self._paragraph.remove_kvpair_element(item)

    def _interpret_value(self, key, value):
        # type: (ParagraphKey, Deb822KeyValuePairElement) -> T
        raise NotImplementedError  # pragma: no cover


# Deb822ParagraphElement uses this Mixin (by having `_paragraph` return self).
# Therefore the Mixin needs to call the "proper" methods on the paragraph to
# avoid doing infinite recursion.
class Deb822ParagraphToStrWrapperMixin(AutoResolvingMixin[str],
                                       collections.abc.MutableMapping[ParagraphKey, str],
                                       ABC):

    @property
    def _auto_map_initial_line_whitespace(self):
        # type: () -> bool
        return True

    @property
    def _discard_comments_on_read(self):
        # type: () -> bool
        return True

    @property
    def _auto_map_final_newline_in_multiline_values(self):
        # type: () -> bool
        return True

    @property
    def _preserve_field_comments_on_field_updates(self):
        # type: () -> bool
        return True

    def _convert_value_to_str(self, kvpair_element):
        # type: (Deb822KeyValuePairElement) -> str
        value_element = kvpair_element.value_element
        value_entries = value_element.value_lines
        if len(value_entries) == 1:
            # Special case single line entry (e.g. "Package: foo") as they never
            # have comments and we can do some parts more efficient.
            value_entry = value_entries[0]
            t = value_entry.convert_to_text()
            if self._auto_map_initial_line_whitespace:
                t = t.strip()
            return t

        if self._auto_map_initial_line_whitespace or self._discard_comments_on_read:
            converter = _convert_value_lines_to_lines(value_entries,
                                                      self._discard_comments_on_read,
                                                      )

            auto_map_space = self._auto_map_initial_line_whitespace

            # Because we know there are more than one line, we can unconditionally inject
            # the newline after the first line
            as_text = ''.join(line.strip() + "\n" if auto_map_space and i == 1 else line
                              for i, line in enumerate(converter, start=1)
                              )
        else:
            # No rewrite necessary.
            as_text = value_element.convert_to_text()

        if self._auto_map_final_newline_in_multiline_values and as_text[-1] == "\n":
            as_text = as_text[:-1]
        return as_text

    def __setitem__(self, item, value):
        # type: (ParagraphKey, str) -> None
        keep_comments = self._preserve_field_comments_on_field_updates  # type: Optional[bool]
        comment = None
        if keep_comments and self._auto_resolve_ambiguous_fields:
            # For ambiguous fields, we have to resolve the original field as
            # the set_field_* methods do not cope with ambiguous fields.  This
            # means we might as well clear the keep_comments flag as we have
            # resolved the comment.
            keep_comments = None
            key_lookup = item
            if isinstance(item, str):
                key_lookup = (item, 0)
            orig_kvpair = self._paragraph.get_kvpair_element(key_lookup, use_get=True)
            if orig_kvpair is not None:
                comment = orig_kvpair.comment_element

        if self._auto_map_initial_line_whitespace:
            try:
                idx = value.index("\n")
            except ValueError:
                idx = -1
            if idx == -1 or idx == len(value):
                self._paragraph.set_field_to_simple_value(
                    item,
                    value.strip(),
                    preserve_original_field_comment=keep_comments,
                    field_comment=comment,
                )
                return
            # Regenerate the first line with normalized whitespace
            first_line, rest = value.split("\n", 1)
            value = "".join((" ", first_line.strip(), "\n", rest))
        if not value.endswith("\n"):
            if not self._auto_map_final_newline_in_multiline_values:
                raise ValueError("Values must end with a newline (or be single line"
                                 " values and use the auto whitespace mapping feature)")
            value += "\n"
        self._paragraph.set_field_from_raw_string(
            item,
            value,
            preserve_original_field_comment=keep_comments,
            field_comment=comment,
        )

    def _interpret_value(self, key, value):
        # type: (ParagraphKey, Deb822KeyValuePairElement) -> T
        # mypy is a bit dense and cannot see that T == str
        return cast('T', self._convert_value_to_str(value))


class AbstractDeb822ParagraphWrapper(AutoResolvingMixin[T], ABC):

    def __init__(self,
                 paragraph,  # type: Deb822ParagraphElement
                 *,
                 auto_resolve_ambiguous_fields=False,  # type: bool
                 ):
        # type: (...) -> None
        self.__paragraph = paragraph
        self.__auto_resolve_ambiguous_fields = auto_resolve_ambiguous_fields

    @property
    def _paragraph(self):
        # type: () -> Deb822ParagraphElement
        return self.__paragraph

    @property
    def _auto_resolve_ambiguous_fields(self):
        # type: () -> bool
        return self.__auto_resolve_ambiguous_fields


class Deb822InterpretingParagraphWrapper(AbstractDeb822ParagraphWrapper[T]):

    def __init__(self,
                 paragraph,  # type: Deb822ParagraphElement
                 interpretation,  # type: Interpretation[T]
                 *,
                 auto_resolve_ambiguous_fields=False,  # type: bool
                 ) -> None:
        super().__init__(paragraph, auto_resolve_ambiguous_fields=auto_resolve_ambiguous_fields)
        self._interpretation = interpretation

    def _interpret_value(self, key, value):
        # type: (ParagraphKey, Deb822KeyValuePairElement) -> T
        return self._interpretation.interpret(value)


class Deb822DictishParagraphWrapper(AbstractDeb822ParagraphWrapper[str],
                                    Deb822ParagraphToStrWrapperMixin):

    def __init__(self,
                 paragraph,  # type: Deb822ParagraphElement
                 *,
                 discard_comments_on_read=True,  # type: bool
                 auto_map_initial_line_whitespace=True,  # type: bool
                 auto_resolve_ambiguous_fields=False,  # type: bool
                 preserve_field_comments_on_field_updates=True,  # type: bool
                 auto_map_final_newline_in_multiline_values=True,  # type: bool
                 ):
        # type: (...) -> None
        super().__init__(paragraph, auto_resolve_ambiguous_fields=auto_resolve_ambiguous_fields)
        self.__discard_comments_on_read = discard_comments_on_read
        self.__auto_map_initial_line_whitespace = auto_map_initial_line_whitespace
        self.__preserve_field_comments_on_field_updates = preserve_field_comments_on_field_updates
        self.__auto_map_final_newline_in_multiline_values = \
            auto_map_final_newline_in_multiline_values

    @property
    def _auto_map_initial_line_whitespace(self):
        # type: () -> bool
        return self.__auto_map_initial_line_whitespace

    @property
    def _discard_comments_on_read(self):
        # type: () -> bool
        return self.__discard_comments_on_read

    @property
    def _preserve_field_comments_on_field_updates(self):
        # type: () -> bool
        return self.__preserve_field_comments_on_field_updates

    @property
    def _auto_map_final_newline_in_multiline_values(self):
        # type: () -> bool
        return self.__auto_map_final_newline_in_multiline_values


class Deb822ParagraphElement(Deb822Element, Deb822ParagraphToStrWrapperMixin, ABC):

    @classmethod
    def from_kvpairs(cls, kvpair_elements):
        # type: (List[Deb822KeyValuePairElement]) -> Deb822ParagraphElement
        if not kvpair_elements:
            raise ValueError("A paragraph must consist of at least one field/value pair")
        kvpair_order = OrderedSet(kv.field_name for kv in kvpair_elements)
        if len(kvpair_order) == len(kvpair_elements):
            # Each field occurs at most once, which is good because that
            # means it is a valid paragraph and we can use the optimized
            # implementation.
            return Deb822ValidParagraphElement(kvpair_elements, kvpair_order)
        # Fallback implementation, that can cope with the repeated field names
        # at the cost of complexity.
        return Deb822InvalidParagraphElement(kvpair_elements)

    def as_interpreted_dict_view(self,
                                 interpretation,  # type: Interpretation[T]
                                 *,
                                 auto_resolve_ambiguous_fields=True,  # type: bool
                                 ):
        # type: (...) -> Deb822InterpretingParagraphWrapper[T]
        r"""Provide a Dict-like view of the paragraph

        This method returns a dict-like object representing this paragraph and
        is useful for accessing fields in a given interpretation. It is possible
        to use multiple versions of this dict-like view with different interpretations
        on the same paragraph at the same time (for different fields).

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... # Field comment (because it becomes just before a field)
            ... Architecture: amd64
            ... # Inline comment (associated with the next line)
            ...               i386
            ... # We also support arm
            ...               arm64
            ...               armel
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> paragraph = next(iter(dfile))
            >>> list_view = paragraph.as_interpreted_dict_view(LIST_SPACE_SEPARATED_INTERPRETATION)
            >>> # With the defaults, you only deal with the semantic values
            >>> # - no leading or trailing whitespace on the first part of the value
            >>> list(list_view["Package"])
            ['foo']
            >>> with list_view["Architecture"] as arch_list:
            ...     orig_arch_list = list(arch_list)
            ...     arch_list.replace('i386', 'kfreebsd-amd64')
            >>> orig_arch_list
            ['amd64', 'i386', 'arm64', 'armel']
            >>> list(list_view["Architecture"])
            ['amd64', 'kfreebsd-amd64', 'arm64', 'armel']
            >>> print(paragraph.convert_to_text(), end='')
            Package: foo
            # Field comment (because it becomes just before a field)
            Architecture: amd64
            # Inline comment (associated with the next line)
                          kfreebsd-amd64
            # We also support arm
                          arm64
                          armel
            >>> # Format preserved and architecture replaced
            >>> with list_view["Architecture"] as arch_list:
            ...     # Prettify the result as sorting will cause awkward whitespace
            ...     arch_list.reformat_when_finished()
            ...     arch_list.sort()
            >>> print(paragraph.convert_to_text(), end='')
            Package: foo
            # Field comment (because it becomes just before a field)
            Architecture: amd64
            # We also support arm
                          arm64
                          armel
            # Inline comment (associated with the next line)
                          kfreebsd-amd64
            >>> list(list_view["Architecture"])
            ['amd64', 'arm64', 'armel', 'kfreebsd-amd64']
            >>> # Format preserved and architecture values sorted

        :param interpretation: Decides how the field values are interpreted.  As an example,
          use LIST_SPACE_SEPARATED_INTERPRETATION for fields such as Architecture in the
          debian/control file.
        :param auto_resolve_ambiguous_fields: This parameter is only relevant for paragraphs
          that contain the same field multiple times (these are generally invalid).  If the
          caller requests an ambiguous field from an invalid paragraph via a plain field name,
          the return dict-like object will refuse to resolve the field (not knowing which
          version to pick).  This parameter (if set to True) instead changes the error into
          assuming the caller wants the *first* variant.
        """
        return Deb822InterpretingParagraphWrapper(
            self,
            interpretation,
            auto_resolve_ambiguous_fields=auto_resolve_ambiguous_fields,
        )

    def configured_view(self,
                        *,
                        discard_comments_on_read=True,  # type: bool
                        auto_map_initial_line_whitespace=True,  # type: bool
                        auto_resolve_ambiguous_fields=True,  # type: bool
                        preserve_field_comments_on_field_updates=True,  # type: bool
                        auto_map_final_newline_in_multiline_values=True,  # type: bool
                        ):
        # type: (...) -> Deb822DictishParagraphWrapper
        r"""Provide a Dict[str, str]-like view of this paragraph with non-standard parameters

        This method returns a dict-like object representing this paragraph that is
        optionally configured differently from the default view.

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... # Field comment (because it becomes just before a field)
            ... Depends: libfoo,
            ... # Inline comment (associated with the next line)
            ...          libbar,
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> paragraph = next(iter(dfile))
            >>> # With the defaults, you only deal with the semantic values
            >>> # - no leading or trailing whitespace on the first part of the value
            >>> paragraph["Package"]
            'foo'
            >>> # - no inline comments in multiline values (but whitespace will be present
            >>> #   subsequent lines.)
            >>> print(paragraph["Depends"])
            libfoo,
                     libbar,
            >>> paragraph['Foo'] = 'bar'
            >>> paragraph.get('Foo')
            'bar'
            >>> paragraph.get('Unknown-Field') is None
            True
            >>> # But you get asymmetric behaviour with set vs. get
            >>> paragraph['Foo'] = ' bar\n'
            >>> paragraph['Foo']
            'bar'
            >>> paragraph['Bar'] = '     bar\n#Comment\n another value\n'
            >>> # Note that the whitespace on the first line has been normalized.
            >>> print("Bar: " + paragraph['Bar'])
            Bar: bar
             another value
            >>> # The comment is present (in case you where wondering)
            >>> print(paragraph.get_kvpair_element('Bar').convert_to_text(), end='')
            Bar: bar
            #Comment
             another value
            >>> # On the other hand, you can choose to see the values as they are
            >>> # - We will just reset the paragraph as a "nothing up my sleeve"
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> paragraph = next(iter(dfile))
            >>> nonstd_dictview = paragraph.configured_view(
            ...     discard_comments_on_read=False,
            ...     auto_map_initial_line_whitespace=False,
            ...     # For paragraphs with duplicate fields, you can choose to get an error
            ...     # rather than the dict picking the first value available.
            ...     auto_resolve_ambiguous_fields=False,
            ...     auto_map_final_newline_in_multiline_values=False,
            ... )
            >>> # Because we have reset the state, Foo and Bar are no longer there.
            >>> 'Bar' not in paragraph and 'Foo' not in paragraph
            True
            >>> # We can now see the comments (discard_comments_on_read=False)
            >>> # (The leading whitespace in front of "libfoo" is due to
            >>> #  auto_map_initial_line_whitespace=False)
            >>> print(nonstd_dictview["Depends"], end='')
             libfoo,
            # Inline comment (associated with the next line)
                     libbar,
            >>> # And all the optional whitespace on the first value line
            >>> # (auto_map_initial_line_whitespace=False)
            >>> nonstd_dictview["Package"] == ' foo\n'
            True
            >>> # ... which will give you symmetric behaviour with set vs. get
            >>> nonstd_dictview['Foo'] = '  bar \n'
            >>> nonstd_dictview['Foo']
            '  bar \n'
            >>> nonstd_dictview['Bar'] = '  bar \n#Comment\n another value\n'
            >>> nonstd_dictview['Bar']
            '  bar \n#Comment\n another value\n'
            >>> # But then you get no help either.
            >>> try:
            ...     nonstd_dictview["Baz"] = "foo"
            ... except ValueError:
            ...     print("Rejected")
            Rejected
            >>> # With auto_map_initial_line_whitespace=False, you have to include minimum a newline
            >>> nonstd_dictview["Baz"] = "foo\n"
            >>> # The absence of leading whitespace gives you the terse variant at the expensive
            >>> # readability
            >>> paragraph.get_kvpair_element('Baz').convert_to_text()
            'Baz:foo\n'
            >>> # But because they are views, changes performed via one view is visible in the other
            >>> paragraph['Foo']
            'bar'
            >>> # The views show the values according to their own rules. Therefore, there is an
            >>> # asymmetric between paragraph['Foo'] and nonstd_dictview['Foo']
            >>> # Nevertheless, you can read or write the fields via either - enabling you to use
            >>> # the view that best suit your use-case for the given field.
            >>> 'Baz' in paragraph and nonstd_dictview.get('Baz') is not None
            True
            >>> # Deletion via the view also works
            >>> del nonstd_dictview['Baz']
            >>> 'Baz' not in paragraph and nonstd_dictview.get('Baz') is None
            True


        :param discard_comments_on_read: When getting a field value from the dict,
          this parameter decides how in-line comments are handled.  When setting
          the value, inline comments are still allowed and will be retained.
          However, keep in mind that this option makes getter and setter assymetric
          as a "get" following a "set" with inline comments will omit the comments
          even if they are there (see the code example).
        :param auto_map_initial_line_whitespace: Special-case the first value line
          by trimming unnecessary whitespace leaving only the value. For single-line
          values, all space including newline is pruned. For multi-line values, the
          newline is preserved / needed to distinguish the first line from the
          following lines.  When setting a value, this option normalizes the
          whitespace of the initial line of the value field.
          When this option is set to True makes the dictionary behave more like the
          original Deb822 module.
        :param preserve_field_comments_on_field_updates: Whether to preserve the field
          comments when mutating the field.
        :param auto_resolve_ambiguous_fields: This parameter is only relevant for paragraphs
          that contain the same field multiple times (these are generally invalid).  If the
          caller requests an ambiguous field from an invalid paragraph via a plain field name,
          the return dict-like object will refuse to resolve the field (not knowing which
          version to pick).  This parameter (if set to True) instead changes the error into
          assuming the caller wants the *first* variant.
        :param auto_map_final_newline_in_multiline_values: This parameter controls whether
          a multiline field with have / need a trailing newline. If True, the trailing
          newline is hidden on get and automatically added in set (if missing).
          When this option is set to True makes the dictionary behave more like the
          original Deb822 module.
        """
        return Deb822DictishParagraphWrapper(
            self,
            discard_comments_on_read=discard_comments_on_read,
            auto_map_initial_line_whitespace=auto_map_initial_line_whitespace,
            auto_resolve_ambiguous_fields=auto_resolve_ambiguous_fields,
            preserve_field_comments_on_field_updates=preserve_field_comments_on_field_updates,
            auto_map_final_newline_in_multiline_values=auto_map_final_newline_in_multiline_values,
        )

    @property
    def _paragraph(self):
        # type: () -> Deb822ParagraphElement
        return self

    @property
    def kvpair_count(self):
        # type: () -> int
        raise NotImplementedError  # pragma: no cover

    def iter_keys(self):
        # type: () -> Iterable[ParagraphKey]
        raise NotImplementedError  # pragma: no cover

    def contains_kvpair_element(self, item):
        # type: (object) -> bool
        raise NotImplementedError  # pragma: no cover

    def get_kvpair_element(self,
                           item,  # type: ParagraphKey
                           use_get=False,  # type: bool
                           ):
        # type: (...) -> Optional[Deb822KeyValuePairElement]
        raise NotImplementedError  # pragma: no cover

    def set_kvpair_element(self, key, value):
        # type: (ParagraphKey, Deb822KeyValuePairElement) -> None
        raise NotImplementedError  # pragma: no cover

    def remove_kvpair_element(self, key):
        # type: (ParagraphKey) -> None
        raise NotImplementedError  # pragma: no cover

    def sort_fields(self,
                    key=None,  # type: Optional[Callable[[str], Any]]
                    ):
        # type: (...) -> None
        raise NotImplementedError  # pragma: no cover

    def set_field_to_simple_value(self,
                                  item,  # type: ParagraphKey
                                  simple_value,  # type: str
                                  *,
                                  preserve_original_field_comment=None,  # type: Optional[bool]
                                  field_comment=None,  # type: Optional[Commentish]
                                  ):
        # type: (...) -> None
        r"""Sets a field in this paragraph to a simple "word" or "phrase"

        In many cases, it is better for callers to just use the paragraph as
        if it was a dictionary.  However, this method does enable to you choose
        the field comment (if any), which can be a reason for using it.

        This is suitable for "simple" fields like "Package".  Example:

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> p = next(iter(dfile))
            >>> p.set_field_to_simple_value("Package", "mscgen")
            >>> p.set_field_to_simple_value("Architecture", "linux-any kfreebsd-any",
            ...                             field_comment=['Only ported to linux and kfreebsd'])
            >>> p.set_field_to_simple_value("Priority", "optional")
            >>> print(p.convert_to_text(), end='')
            Package: mscgen
            # Only ported to linux and kfreebsd
            Architecture: linux-any kfreebsd-any
            Priority: optional
            >>> # Values are formatted nicely by default, but it does not work with
            >>> # multi-line values
            >>> p.set_field_to_simple_value("Foo", "bar\nbin\n")
            Traceback (most recent call last):
                ...
            ValueError: Cannot use set_field_to_simple_value for values with newlines

        :param item: Name of the field to set.  If the paragraph already
          contains the field, then it will be replaced.  If the field exists,
          then it will preserve its order in the paragraph.  Otherwise, it is
          added to the end of the paragraph.
          Note this can be a "paragraph key", which enables you to control
          *which* instance of a field is being replaced (in case of duplicate
          fields).
        :param simple_value: The text to use as the value.  The value must not
          contain newlines.  Leading and trailing will be stripped but space
          within the value is preserved.  The value cannot contain comments
          (i.e. if the "#" token appears in the value, then it is considered
          a value rather than "start of a comment)
        :param preserve_original_field_comment: See the description for the
          parameter with the same name in the set_field_from_raw_string method.
        :param field_comment: See the description for the parameter with the same
          name in the set_field_from_raw_string method.
        """
        if '\n' in simple_value:
            raise ValueError("Cannot use set_field_to_simple_value for values with newlines")

        # Reformat it with a leading space and trailing newline. The latter because it is
        # necessary if there any fields after it and the former because it looks nicer so
        # have single space after the field separator
        raw_value = ' ' + simple_value.strip() + "\n"
        self.set_field_from_raw_string(
            item,
            raw_value,
            preserve_original_field_comment=preserve_original_field_comment,
            field_comment=field_comment,
        )

    def set_field_from_raw_string(self,
                                  item,  # type: ParagraphKey
                                  raw_string_value,  # type: str
                                  *,
                                  preserve_original_field_comment=None,  # type: Optional[bool]
                                  field_comment=None,  # type: Optional[Commentish]
                                  ):
        # type: (...) -> None
        """Sets a field in this paragraph to a given text value

        In many cases, it is better for callers to just use the paragraph as
        if it was a dictionary.  However, this method does enable to you choose
        the field comment (if any) and lets to have a higher degree of control
        over whitespace (on the first line), which can be a reason for using it.

        Example usage:

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> p = next(iter(dfile))
            >>> raw_value = '''
            ... Build-Depends: debhelper-compat (= 12),
            ...                some-other-bd,
            ... # Comment
            ...                another-bd,
            ... '''.lstrip()  # Remove leading newline, but *not* the trailing newline
            >>> fname, new_value = raw_value.split(':', 1)
            >>> p.set_field_from_raw_string(fname, new_value)
            >>> print(p.convert_to_text(), end='')
            Package: foo
            Build-Depends: debhelper-compat (= 12),
                           some-other-bd,
            # Comment
                           another-bd,
            >>> # Format preserved

        :param item: Name of the field to set.  If the paragraph already
          contains the field, then it will be replaced.  Otherwise, it is
          added to the end of the paragraph.
          Note this can be a "paragraph key", which enables you to control
          *which* instance of a field is being replaced (in case of duplicate
          fields).
        :param raw_string_value: The text to use as the value.  The text must
          be valid deb822 syntax and is used *exactly* as it is given.
          Accordingly, multi-line values must include mandatory leading space
          on continuation lines, newlines after the value, etc. On the
          flip-side, any optional space or comments will be included.

          Note that the first line will *never* be read as a comment (if the
          first line of the value starts with a "#" then it will result
          in "Field-Name:#..." which is parsed as a value starting with "#"
          rather than a comment).
        :param preserve_original_field_comment: If True, then if there is an
          existing field and that has a comment, then the comment will remain
          after this operation.  This is the default is the `field_comment`
          parameter is omitted.
        :param field_comment: If not None, add or replace the comment for
          the field.  Each string in the in the list will become one comment
          line (inserted directly before the field name). Will appear in the
          same order as they do in the list.

          If you want complete control over the formatting of the comments,
          then ensure that each line start with "#" and end with "\\n" before
          the call.  Otherwise, leading/trailing whitespace is normalized
          and the missing "#"/"\\n" character is inserted.
        """

        new_content = []  # type: List[str]
        if preserve_original_field_comment is not None:
            if field_comment is not None:
                raise ValueError('The "preserve_original_field_comment" conflicts with'
                                 ' "field_comment" parameter')
        elif field_comment is not None:
            if not isinstance(field_comment, Deb822CommentElement):
                new_content.extend(_format_comment(x) for x in field_comment)
                field_comment = None
        else:
            preserve_original_field_comment = True

        field_name, _ = _unpack_key(item, resolve_field_name=True)
        field_name = cast('str', field_name)

        raw = ":".join((field_name, raw_string_value))  # FIXME
        raw_lines = raw.splitlines(keepends=True)
        for i, line in enumerate(raw_lines, start=1):
            if not line.endswith("\n"):
                raise ValueError("Line {i} in new value was missing trailing newline".format(i=i))
            if i != 1 and line[0] not in (' ', '#'):
                msg = 'Line {i} in new value was invalid.  It must either start' \
                      ' with " " space (continuation line) or "#" (comment line).' \
                      ' The line started with "{line}"'
                raise ValueError(msg.format(i=i, line=line[0]))
        if len(raw_lines) > 1 and raw_lines[-1].startswith('#'):
            raise ValueError('The last line in a value field cannot be a comment')
        new_content.extend(raw_lines)
        # As absurd as it might seem, it is easier to just use the parser to
        # construct the AST correctly
        deb822_file = parse_deb822_file(iter(new_content))
        error_token = deb822_file.find_first_error_element()
        if error_token:
            raise ValueError("Syntax error in new field value for " + field_name)
        paragraph = next(iter(deb822_file))
        assert isinstance(paragraph, Deb822ValidParagraphElement)
        value = paragraph.get_kvpair_element(field_name)
        assert value is not None
        if preserve_original_field_comment:
            original = self.get_kvpair_element(item, use_get=True)
            if original:
                value.comment_element = original.comment_element
                original.comment_element = None
        elif field_comment is not None:
            value.comment_element = field_comment
        self.set_kvpair_element(item, value)


class Deb822ValidParagraphElement(Deb822ParagraphElement):
    """Paragraph implementation optimized for valid deb822 files

    When there are no duplicated fields, we can use simpler and faster
    datastructures for common operations.
    """

    def __init__(self,
                 kvpair_elements,  # type: List[Deb822KeyValuePairElement]
                 kvpair_order,  # type: OrderedSet
                 ):
        # type: (...) -> None
        super().__init__()
        self._kvpair_elements = {kv.field_name: kv for kv in kvpair_elements}
        self._kvpair_order = kvpair_order
        self._init_parent_of_parts()

    @property
    def kvpair_count(self):
        # type: () -> int
        return len(self._kvpair_elements)

    def iter_keys(self):
        # type: () -> Iterable[ParagraphKey]
        yield from self._kvpair_elements

    def remove_kvpair_element(self, key):
        # type: (ParagraphKey) -> None
        key, _ = _unpack_key(key, resolve_field_name=True, raise_if_indexed=True)
        key = cast('_strI', key)
        del self._kvpair_elements[key]

    def contains_kvpair_element(self, item):
        # type: (object) -> bool
        if not isinstance(item, (str, tuple, Deb822FieldNameToken)):
            return False
        item = cast('ParagraphKey', item)
        key, _ = _unpack_key(item, resolve_field_name=True, raise_if_indexed=True)
        key = cast('_strI', key)
        return key in self._kvpair_elements

    def get_kvpair_element(self,
                           item,  # type: ParagraphKey
                           use_get=False,  # type: bool
                           ):
        # type: (...) -> Optional[Deb822KeyValuePairElement]
        item, _ = _unpack_key(item, resolve_field_name=True, raise_if_indexed=True)
        item = cast('_strI', item)
        if use_get:
            return self._kvpair_elements.get(item)
        return self._kvpair_elements[item]

    def set_kvpair_element(self, key, value):
        # type: (ParagraphKey, Deb822KeyValuePairElement) -> None
        key, _ = _unpack_key(key, raise_if_indexed=True)
        if isinstance(key, Deb822FieldNameToken):
            if key is not value.field_token:
                raise ValueError("Key is a Deb822FieldNameToken, but not *the* Deb822FieldNameToken"
                                 " for the value")
            key = value.field_name
        else:
            if key != value.field_name:
                raise ValueError("Cannot insert value under a different field value than field name"
                                 " from its Deb822FieldNameToken implies")
            # Use the string from the Deb822FieldNameToken as it is a _strI
            key = value.field_name
        original_value = self._kvpair_elements.get(key)
        self._kvpair_elements[key] = value
        self._kvpair_order.append(key)
        if original_value is not None:
            original_value.parent_element = None
        value.parent_element = self

    def sort_fields(self, key=None):
        # type: (Optional[Callable[[str], Any]]) -> None
        for last_field_name in reversed(self._kvpair_order):
            last_kvpair = self._kvpair_elements[cast('_strI', last_field_name)]
            last_kvpair.value_element.add_final_newline_if_missing()
            break

        self._kvpair_order = OrderedSet(sorted(self._kvpair_order, key=key))

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        yield from (self._kvpair_elements[x]
                    for x in cast('Iterable[_strI]', self._kvpair_order))


class Deb822InvalidParagraphElement(Deb822ParagraphElement):

    def __init__(self, kvpair_elements):
        # type: (List[Deb822KeyValuePairElement]) -> None
        super().__init__()
        self._kvpair_order = LinkedList()  # type: LinkedList[Deb822KeyValuePairElement]
        self._kvpair_elements = \
            {}  # type: Dict[_strI, List[LinkedListNode[Deb822KeyValuePairElement]]]
        self._init_kvpair_fields(kvpair_elements)
        self._init_parent_of_parts()

    def _init_kvpair_fields(self, kvpairs):
        # type: (Iterable[Deb822KeyValuePairElement]) -> None
        assert not self._kvpair_order
        assert not self._kvpair_elements
        for kv in kvpairs:
            field_name = kv.field_name
            node = self._kvpair_order.append(kv)
            if field_name not in self._kvpair_elements:
                self._kvpair_elements[field_name] = [node]
            else:
                self._kvpair_elements[field_name].append(node)

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        yield from self._kvpair_order

    @property
    def kvpair_count(self):
        # type: () -> int
        return len(self._kvpair_order)

    def iter_keys(self):
        # type: () -> Iterable[ParagraphKey]
        yield from (kv.field_name for kv in self._kvpair_order)

    def get_kvpair_element(self,
                           item,  # type: ParagraphKey
                           use_get=False,  # type: bool
                           ):
        # type: (...) -> Optional[Deb822KeyValuePairElement]
        name_token = None  # type: Optional[Deb822FieldNameToken]
        key, index = _unpack_key(item)
        if isinstance(key, Deb822FieldNameToken):
            name_token = key
            key = name_token.text
        else:
            name_token = None
            key = _strI(key)
        if use_get:
            res = self._kvpair_elements.get(key)
            if res is None:
                return None
        else:
            res = self._kvpair_elements[key]
        if index is None:
            if len(res) != 1:
                if name_token is not None:
                    node = self._find_node_via_name_token(name_token, res)
                    if node is not None:
                        return node.value
                msg = "Ambiguous key {key} - the field appears {res_len} times. Use" \
                      " ({key}, index) to denote which instance of the field you want.  (Index" \
                      " can be 0..{res_len_1} or e.g. -1 to denote the last field)"
                # res_len=len(res)
                # res_len_1=len(res) - 1
                raise AmbiguousDeb822FieldKeyError(msg.format(key=key,
                                                              res_len=len(res),
                                                              res_len_1=len(res) - 1))
            index = 0
        try:
            return res[index].value
        except IndexError:
            if use_get:
                return None
            msg = 'Field "{key}" was present but the index "{index}" was invalid.'
            raise KeyError(msg.format(key=key, index=index))

    @staticmethod
    def _find_node_via_name_token(
            name_token,  # type: Deb822FieldNameToken
            elements,  # type: Iterable[LinkedListNode[Deb822KeyValuePairElement]]
    ):
        # type: (...) -> Optional[LinkedListNode[Deb822KeyValuePairElement]]
        # if we are given a name token, then it is non-ambiguous if we have exactly
        # that name token in our list of nodes.  It will be an O(n) lookup but we
        # probably do not have that many duplicate fields (and even if do, it is not
        # exactly a valid file, so there little reason to optimize for it)
        for node in elements:
            if name_token is node.value.field_token:
                return node
        return None

    def contains_kvpair_element(self, item):
        # type: (object) -> bool
        if not isinstance(item, (str, tuple, Deb822FieldNameToken)):
            return False
        item = cast('ParagraphKey', item)
        return self.get_kvpair_element(item, use_get=True) is not None

    def set_kvpair_element(self, key, value):
        # type: (ParagraphKey, Deb822KeyValuePairElement) -> None
        key, index = _unpack_key(key)
        if isinstance(key, Deb822FieldNameToken):
            if key is not value.field_token:
                original_nodes = self._kvpair_elements.get(value.field_name)
                original_node = None
                if original_nodes is not None:
                    original_node = self._find_node_via_name_token(key, original_nodes)

                if original_node is None:
                    raise ValueError("Key is a Deb822FieldNameToken, but not *the*"
                                     " Deb822FieldNameToken for the value nor the"
                                     " Deb822FieldNameToken for an existing field in the paragraph")
                # Primarily for mypy's sake
                assert original_nodes is not None
                # Rely on the index-based code below to handle update.
                index = original_nodes.index(original_node)
            key = value.field_name
        else:
            if key != value.field_name:
                raise ValueError("Cannot insert value under a different field value than field name"
                                 " from its Deb822FieldNameToken implies")
            # Use the string from the Deb822FieldNameToken as it is a _strI
            key = value.field_name
        original_nodes = self._kvpair_elements.get(key)
        if original_nodes is None or not original_nodes:
            if index is not None and index != 0:
                msg = "Cannot replace field ({key}, {index}) as the field does not exist" \
                      " in the first place.  Please index-less key or ({key}, 0) if you" \
                      " want to add the field."
                raise KeyError(msg.format(key=key, index=index))
            node = self._kvpair_order.append(value)
            if key not in self._kvpair_elements:
                self._kvpair_elements[key] = [node]
            else:
                self._kvpair_elements[key].append(node)
            return

        replace_all = False
        if index is None:
            replace_all = True
            node = original_nodes[0]
            if len(original_nodes) != 1:
                self._kvpair_elements[key] = [node]
        else:
            # We insist on there being an original node, which as a side effect ensures
            # you cannot add additional copies of the field.  This means that you cannot
            # make the problem worse.
            node = original_nodes[index]

        # Replace the value of the existing node plus do a little dance
        # for the parent element part.
        node.value.parent_element = None
        value.parent_element = self
        node.value = value

        if replace_all and len(original_nodes) != 1:
            # If we were in a replace-all mode, discard any remaining nodes
            for n in original_nodes[1:]:
                n.value.parent_element = None
                self._kvpair_order.remove_node(n)

    def remove_kvpair_element(self, key):
        # type: (ParagraphKey) -> None
        key, idx = _unpack_key(key)
        name_token = None  # type: Optional[Deb822FieldNameToken]
        if isinstance(key, Deb822FieldNameToken):
            name_token = key
            key = name_token.text
        else:
            name_token = None
            key = _strI(key)
        field_list = self._kvpair_elements[key]

        if name_token is None and idx is None:
            # Remove all case
            for node in field_list:
                node.value.parent_element = None
                self._kvpair_order.remove_node(node)
            del self._kvpair_elements[key]
            return

        if name_token is not None:
            # Indirection between original_node and node for mypy's sake
            original_node = self._find_node_via_name_token(name_token, field_list)
            if original_node is None:
                msg = 'The field "{key}" is present but key used to access it is not.'
                raise KeyError(msg.format(key=key))
            node = original_node
        else:
            assert idx is not None
            try:
                node = field_list[idx]
            except KeyError:
                msg = 'The field "{key}" is present, but the index "{idx}" was invalid.'
                raise KeyError(msg.format(key=key, idx=idx))

        if len(field_list) == 1:
            del self._kvpair_elements[key]
        else:
            field_list.remove(node)
        node.value.parent_element = None
        self._kvpair_order.remove_node(node)

    def sort_fields(self, key=None):
        # type: (Optional[Callable[[str], Any]]) -> None
        if key is None:
            actual_key = operator.attrgetter(
                'field_name')  # type: Callable[[Deb822KeyValuePairElement], Any]
        else:
            # Work around mypy that cannot seem to shred the Optional notion
            # without this little indirection
            key_impl = key

            def _actual_key(kvpair):
                # type: (Deb822KeyValuePairElement) -> Any
                return key_impl(kvpair.field_name)

            actual_key = _actual_key
        for last_kvpair in reversed(self._kvpair_order):
            last_kvpair.value_element.add_final_newline_if_missing()
            break

        sorted_kvpair_list = sorted(self._kvpair_order, key=actual_key)
        self._kvpair_order = LinkedList()
        self._kvpair_elements = {}
        self._init_kvpair_fields(sorted_kvpair_list)


class Deb822FileElement(Deb822Element):
    """Represents the entire deb822 file"""

    def __init__(self, token_and_elements):
        # type: (List[TokenOrElement]) -> None
        super().__init__()
        self._token_and_elements = token_and_elements
        self._init_parent_of_parts()

    @property
    def is_valid_file(self):
        # type: () -> bool
        """Returns true if the file is valid

        Invalid elements include error elements (Deb822ErrorElement) but also
        issues such as paragraphs with duplicate fields or "empty" files
        (a valid deb822 file contains at least one paragraph).
        """
        paragraphs = list(self)
        if not paragraphs:
            return False
        if any(p for p in paragraphs if not isinstance(p, Deb822ValidParagraphElement)):
            return False
        return self.find_first_error_element() is None

    def find_first_error_element(self):
        # type: () -> Optional[Deb822ErrorElement]
        """Returns the first Deb822ErrorElement (or None) in the file"""
        return next(iter(self.iter_recurse(only_element_or_token_type=Deb822ErrorElement)), None)

    def __iter__(self):
        # type: () -> Iterator[Deb822ParagraphElement]
        return iter(self.iter_parts_of_type(Deb822ParagraphElement))

    def iter_parts(self):
        # type: () -> Iterable[TokenOrElement]
        yield from self._token_and_elements

    def dump(self, fd):
        # type: (IO[bytes]) -> None
        for token in self.iter_tokens():
            fd.write(token.text.encode('utf-8'))


_combine_error_tokens_into_elements = combine_into_replacement(Deb822ErrorToken, Deb822ErrorElement)
_combine_comment_tokens_into_elements = combine_into_replacement(Deb822CommentToken,
                                                                 Deb822CommentElement)
_combine_vl_elements_into_value_elements = combine_into_replacement(Deb822ValueLineElement,
                                                                    Deb822ValueElement)
_combine_kvp_elements_into_paragraphs = combine_into_replacement(
    Deb822KeyValuePairElement,
    Deb822ParagraphElement,
    constructor=Deb822ParagraphElement.from_kvpairs
    )


LIST_SPACE_SEPARATED_INTERPRETATION = ListInterpretation(_whitespace_separated_list_of_tokens,
                                                         Deb822ValueToken,
                                                         Deb822SemanticallySignificantWhiteSpace,
                                                         lambda: Deb822SpaceSeparatorToken(' '),
                                                         )
LIST_COMMA_SEPARATED_INTERPRETATION = ListInterpretation(_comma_separated_list_of_tokens,
                                                         Deb822ValueToken,
                                                         Deb822CommaToken,
                                                         Deb822CommaToken,
                                                         )


def _non_end_of_line_token(v):
    # type: (TokenOrElement) -> bool
    # Consume tokens until the newline
    return not isinstance(v, Deb822WhitespaceToken) or v.text != '\n'


def _build_value_line(token_stream,  # type: Iterable[Union[TokenOrElement, Deb822CommentElement]]
                      ):
    # type: (...) -> Iterable[Union[TokenOrElement, Deb822ValueLineElement]]
    """Parser helper - consumes tokens part of a Deb822ValueEntryElement and turns them into one"""
    buffered_stream = BufferingIterator(token_stream)

    # Deb822ValueLineElement is a bit tricky because of how we handle whitespace
    # and comments.
    #
    # In relation to comments, then only continuation lines can have comments.
    # If there is a comment before a "K: V" line, then the comment is associated
    # with the field rather than the value.
    #
    # On the whitespace front, then we separate syntactical mandatory whitespace
    # from optional whitespace.  As an example:
    #
    # """
    # # some comment associated with the Depends field
    # Depends:_foo_$
    # # some comment associated with the line containing "bar"
    # !________bar_$
    # """
    #
    # Where "$" and "!" represents mandatory whitespace (the newline and the first
    # space are required for the file to be parsed correctly), where as "_" is
    # "optional" whitespace (from a syntactical point of view).
    #
    # This distinction enable us to facilitate APIs for easy removal/normalization
    # of redundant whitespaces without having programmers worry about trashing
    # the file.
    #
    #

    comment_element = None
    continuation_line_token = None
    token = None  # type: Optional[TokenOrElement]

    for token in buffered_stream:
        start_of_value_entry = False
        if isinstance(token, Deb822CommentElement):
            next_token = buffered_stream.peek()
            # If the next token is a continuation line token, then this comment
            # belong to a value and we might as well just start the value
            # parsing now.
            #
            # Note that we rely on this behaviour to avoid emitting the comment
            # token (failing to do so would cause the comment to appear twice
            # in the file).
            if isinstance(next_token, Deb822ValueContinuationToken):
                start_of_value_entry = True
                comment_element = token
                token = None
                # Use next with None to avoid raising StopIteration inside a generator
                # It won't happen, but pylint cannot see that, so we do this instead.
                continuation_line_token = cast('Deb822ValueContinuationToken',
                                               next(buffered_stream, None)
                                               )
                assert continuation_line_token is not None
        elif isinstance(token, Deb822ValueContinuationToken):
            continuation_line_token = token
            start_of_value_entry = True
            token = None
        elif isinstance(token, Deb822FieldSeparatorToken):
            start_of_value_entry = True

        if token is not None:
            yield token
        if start_of_value_entry:
            tokens_in_value = list(buffered_stream.takewhile(_non_end_of_line_token))
            eol_token = cast('Deb822WhitespaceToken', next(buffered_stream, None))
            assert eol_token is None or eol_token.text == '\n'
            leading_whitespace = None
            trailing_whitespace = None
            # "Depends:\n foo" would cause tokens_in_value to be empty for the
            # first "value line" (the empty part between ":" and "\n")
            if tokens_in_value:
                # Another special-case, "Depends: \n foo" (i.e. space after colon)
                # should not introduce an IndexError
                if isinstance(tokens_in_value[-1], Deb822WhitespaceToken):
                    trailing_whitespace = cast('Deb822WhitespaceToken',
                                               tokens_in_value.pop()
                                               )
                if tokens_in_value and isinstance(tokens_in_value[-1], Deb822WhitespaceToken):
                    leading_whitespace = cast('Deb822WhitespaceToken', tokens_in_value[0])
                    tokens_in_value = tokens_in_value[1:]
            yield Deb822ValueLineElement(comment_element,
                                         continuation_line_token,
                                         leading_whitespace,
                                         tokens_in_value,
                                         trailing_whitespace,
                                         eol_token
                                         )
            comment_element = None
            continuation_line_token = None


def _build_field_with_value(
        token_stream  # type: Iterable[Union[TokenOrElement, Deb822ValueElement]]
    ):
    # type: (...) -> Iterable[Union[TokenOrElement, Deb822KeyValuePairElement]]
    buffered_stream = BufferingIterator(token_stream)
    for token_or_element in buffered_stream:
        start_of_field = False
        comment_element = None
        if isinstance(token_or_element, Deb822CommentElement):
            comment_element = token_or_element
            next_token = buffered_stream.peek()
            start_of_field = isinstance(next_token, Deb822FieldNameToken)
            if start_of_field:
                # Remember to consume the field token, the we are aligned
                try:
                    token_or_element = next(buffered_stream)
                except StopIteration:  # pragma: no cover
                    raise AssertionError
        elif isinstance(token_or_element, Deb822FieldNameToken):
            start_of_field = True

        if start_of_field:
            field_name = token_or_element
            next_tokens = buffered_stream.peek_many(2)
            if len(next_tokens) < 2:
                # Early EOF - should not be possible with how the tokenizer works
                # right now, but now it is future proof.
                if comment_element:
                    yield comment_element
                error_elements = [field_name]
                error_elements.extend(buffered_stream)
                yield Deb822ErrorElement(error_elements)
                return
            separator, value_element = next_tokens

            if isinstance(separator, Deb822FieldSeparatorToken) \
                    and isinstance(value_element, Deb822ValueElement):
                # Consume the two tokens to align the stream
                next(buffered_stream, None)
                next(buffered_stream, None)

                yield Deb822KeyValuePairElement(comment_element,
                                                cast('Deb822FieldNameToken', field_name),
                                                separator,
                                                value_element,
                                                )
            else:
                # We had a parse error, consume until the newline.
                error_tokens = [token_or_element]  # type: List[TokenOrElement]
                error_tokens.extend(buffered_stream.takewhile(_non_end_of_line_token))
                nl = buffered_stream.peek()
                # Take the newline as well if present
                if nl and isinstance(nl, Deb822NewlineAfterValueToken):
                    error_tokens.append(nl)
                yield Deb822ErrorElement(error_tokens)
        else:
            # Token is not part of a field, emit it as-is
            yield token_or_element


def parse_deb822_file(sequence,  # type: Iterable[Union[str, bytes]]
                      *,
                      accept_files_with_error_tokens=False,  # type: bool
                      accept_files_with_duplicated_fields=True  # type: bool
                      ):
    # type: (...) -> Deb822FileElement
    """

    :param sequence: An iterable over lines of str or bytes (an open file for
      reading will do).  The lines must include the trailing line ending ("\\n").
    :param accept_files_with_error_tokens: If True, files with critical syntax
      or parse errors will be returned as "successfully" parsed. Usually,
      working on files with these kind of errors are not desirable as it is
      hard to make sense of such files (and they might in fact not be a deb822
      file at all).  When set to False (the default) a ValueError is raised if
      there is a critical syntax or parse error.
      Note that duplicated fields in a paragraph is not considered a critical
      parse error by this parser as the implementation can gracefully cope
      with these. Use accept_files_with_duplicated_fields to determine if
      such files should be accepted.
    :param accept_files_with_duplicated_fields: If True (the default), then
      files containing paragraphs with duplicated fields will be returned as
      "successfully" parsed even though they are invalid according to the
      specification.  The paragraphs will prefer the first appearance of the
      field unless caller explicitly requests otherwise (e.g., via
      Deb822ParagraphElement.configured_view).  If False, then this method
      will raise a ValueError if any duplicated fields are seen inside any
      paragraph.
    """
    # The order of operations are important here.  As an example,
    # _build_value_line assumes that all comment tokens have been merged
    # into comment elements.  Likewise, _build_field_and_value assumes
    # that value tokens (along with their comments) have been combined
    # into elements.
    tokens = tokenize_deb822_file(sequence)  # type: Iterable[TokenOrElement]
    tokens = _combine_comment_tokens_into_elements(tokens)
    tokens = _build_value_line(tokens)
    tokens = _combine_vl_elements_into_value_elements(tokens)
    tokens = _build_field_with_value(tokens)
    tokens = _combine_kvp_elements_into_paragraphs(tokens)
    # Combine any free-floating error tokens into error elements.  We do
    # this last as it enable other parts of the parser to include error
    # tokens in their error elements if they discover something is wrong.
    tokens = _combine_error_tokens_into_elements(tokens)

    deb822_file = Deb822FileElement(list(tokens))

    if not accept_files_with_error_tokens:
        error_element = deb822_file.find_first_error_element()
        if error_element is not None:
            error_as_text = error_element.convert_to_text().replace('\n', '\\n')
            raise ValueError('Syntax or Parse error on the line: "{error_as_text}"'.format(
                error_as_text=error_as_text
            ))

    if not accept_files_with_duplicated_fields:
        for no, paragraph in enumerate(deb822_file):
            if isinstance(paragraph, Deb822InvalidParagraphElement):
                field_names = set()
                dup_field = None
                for field in paragraph.keys():
                    field_name, _ = _unpack_key(field, resolve_field_name=True)
                    # assert for mypy
                    assert isinstance(field_name, str)
                    if field_name in field_names:
                        dup_field = field_name
                        break
                    field_names.add(field_name)
                if dup_field is not None:
                    msg = 'Duplicate field "{dup_field}" in paragraph number {no}'
                    raise ValueError(msg.format(dup_field=dup_field, no=no))

    return deb822_file


if __name__ == "__main__":  # pragma: no cover
    import doctest
    doctest.testmod()
