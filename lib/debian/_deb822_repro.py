import collections
import collections.abc
import contextlib
import operator
import re
import sys
import typing
import weakref
from abc import ABC
from types import TracebackType
from typing import Iterable, Iterator, List, Union, Dict, Optional, TypeVar, Callable, Any, Generic
from weakref import ReferenceType

from .deb822 import _strI, OrderedSet


T = TypeVar('T')
TokenOrElement = Union['Deb822Element', 'Deb822Token']
E = TypeVar('E', bound=TokenOrElement)
R = TypeVar('R', bound='Deb822Element')
S = TypeVar('S', bound=TokenOrElement)

VT = TypeVar('VT', bound='Deb822Token')
ST = TypeVar('ST', bound='Deb822Token')
ParagraphKeyBase = Union['Deb822FieldNameToken', str]
ParagraphKey = Union[ParagraphKeyBase, typing.Tuple[str, int]]
Commentish = Union[List[str], 'Deb822CommentElement']


_RE_WHITESPACE_LINE = re.compile(r'^\s+$')
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

# From Policy 5.1:
#
#    The field name is composed of US-ASCII characters excluding control
#    characters, space, and colon (i.e., characters in the ranges U+0021
#    (!) through U+0039 (9), and U+003B (;) through U+007E (~),
#    inclusive). Field names must not begin with the comment character
#    (U+0023 #), nor with the hyphen character (U+002D -).
#
# That combines to this regex of questionable readability
_RE_FIELD_LINE = re.compile(r'''
    ^                                          # Start of line
    (?P<field_name>                            # Capture group for the field name
        [\x21\x22\x24-\x2C\x2F-\x39\x3B-\x7F]  # First character
        [\x21-\x39\x3B-\x7F]*                  # Subsequent characters (if any)
    )
    (?P<separator> : )
    (?P<space_before_value> \s* )
    (?:                                        # Field values are not mandatory on the same line
                                               # as the field name.

      (?P<value>  \S(?:.*\S)?  )               # Values must start and end on a "non-space"
      (?P<space_after_value> \s* )             # We can have optional space after the value
    )?
''', re.VERBOSE)


class AmbiguousDeb822FieldKeyError(KeyError):
    pass


def _resolve_ref(ref: Optional[ReferenceType[T]]) -> Optional[T]:
    return ref() if ref is not None else None


class _LinkedListNode(Generic[T]):

    __slots__ = ('_previous_node', 'value', 'next_node', '__weakref__')

    def __init__(self, value: T):
        self._previous_node: 'Optional[ReferenceType[_LinkedListNode[T]]]' = None
        self.next_node: 'Optional[_LinkedListNode[T]]' = None
        self.value = value

    @property
    def previous_node(self) -> 'Optional[_LinkedListNode[T]]':
        return _resolve_ref(self._previous_node)

    @previous_node.setter
    def previous_node(self, node: '_LinkedListNode[T]') -> None:
        self._previous_node = weakref.ref(node) if node is not None else None

    def remove(self) -> T:
        _LinkedListNode.link_nodes(self.previous_node, self.next_node)
        self.previous_node = None
        self.next_node = None
        return self.value

    def iter_next(self, *, skip_current: bool = False) -> Iterator['_LinkedListNode[T]']:
        node = self.next_node if skip_current else self
        while node:
            yield node
            node = node.next_node

    def iter_previous(self, *, skip_current: bool = False) -> Iterator['_LinkedListNode[T]']:
        node = self.previous_node if skip_current else self
        while node:
            yield node
            node = node.previous_node

    @staticmethod
    def link_nodes(previous_node: Optional['_LinkedListNode[T]'],
                   next_node: Optional['_LinkedListNode[T]']) -> None:
        if next_node:
            next_node.previous_node = previous_node
        if previous_node:
            previous_node.next_node = next_node

    @staticmethod
    def _insert_link(first_node: Optional['_LinkedListNode[T]'],
                     new_node: '_LinkedListNode[T]',
                     last_node: Optional['_LinkedListNode[T]']
                     ) -> None:
        _LinkedListNode.link_nodes(first_node, new_node)
        _LinkedListNode.link_nodes(new_node, last_node)

    def insert_after(self, new_node: '_LinkedListNode[T]') -> None:
        assert self is not new_node and new_node is not self.next_node
        _LinkedListNode._insert_link(self, new_node, self.next_node)


class _LinkedList(Generic[T]):
    """Specialized linked list implementation to support the deb822 parser needs

    We deliberately trade "encapsulation" for features needed by the by this library
    to facilitate their implementation.  Notably, we allow nodes to leak and assume
    well-behaved calls to remove_node - because that makes it easier to implement
    components like Deb822InvalidParagraphElement.
    """

    __slots__ = ('head_node', 'tail_node')

    def __init__(self, values: Optional[Iterable[T]] = None, /) -> None:
        self.head_node: Optional[_LinkedListNode[T]] = None
        self.tail_node: Optional[_LinkedListNode[T]] = None
        if values is not None:
            self.extend(values)

    def __bool__(self) -> bool:
        return self.head_node is not None

    @property
    def tail(self) -> Optional[T]:
        return self.tail_node.value if self.tail_node is not None else None

    def pop(self) -> None:
        if self.tail_node is None:
            raise IndexError('pop from empty list')
        self.remove_node(self.tail_node)

    def iter_nodes(self) -> typing.Iterator[_LinkedListNode[T]]:
        head_node = self.head_node
        if head_node is None:
            return
        yield from head_node.iter_next()

    def __iter__(self) -> typing.Iterator[T]:
        yield from (node.value for node in self.iter_nodes())

    def __reversed__(self) -> typing.Iterator[T]:
        tail_node = self.tail_node
        if tail_node is None:
            return
        yield from (n.value for n in tail_node.iter_previous())

    def remove_node(self, node: _LinkedListNode[T]) -> None:
        if node is self.head_node:
            self.head_node = node.next_node
            if self.head_node is None:
                self.tail_node = None
        elif node is self.tail_node:
            self.tail_node = node.previous_node
            # That case should have happened in the "if node is self._head"
            # part
            assert self.tail_node is not None
        node.remove()

    def append(self, value: T) -> _LinkedListNode[T]:
        node = _LinkedListNode(value)
        if self.head_node is None:
            self.head_node = node
            self.tail_node = node
        else:
            # Primarily as a hint to mypy
            assert self.tail_node is not None
            self.tail_node.insert_after(node)
            self.tail_node = node
        return node

    def extend(self, values: Iterable[T]) -> None:
        for v in values:
            self.append(v)

    def clear(self) -> None:
        self.head_node = None
        self.tail_node = None


class Deb822ParsedTokenList(Generic[VT, ST],
                            contextlib.AbstractContextManager['Deb822ParsedTokenList[VT, ST]']
                            ):

    def __init__(self,
                 kvpair_element: 'Deb822KeyValuePairElement',
                 interpreted_value_element: 'List[Deb822Token]',
                 vtype: typing.Type[VT],
                 stype: typing.Type[ST],
                 tokenizer: Callable[[str], Iterable['Deb822Token']],
                 default_separator_factory: Callable[[], ST],
                 ) -> None:
        self._kvpair_element = kvpair_element
        self._token_list = _LinkedList(interpreted_value_element)
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

    def __iter__(self) -> Iterator[E]:
        yield from (v for v in self._token_list if isinstance(v, self._vtype))

    def __bool__(self) -> bool:
        return next(iter(self), None) is not None

    def __exit__(self,
                 exc_type: Optional[typing.Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]
                 ) -> Optional[bool]:
        if exc_type is None and self._changed:
            self._update_field()
        return super().__exit__(exc_type, exc_val, exc_tb)

    def append_separator(self,
                         space_after_separator: bool = True) -> None:

        separator_token = self._default_separator_factory()
        if separator_token.is_whitespace:
            space_after_separator = False

        self._changed = True
        self._append_continuation_line_token_if_necessary()
        self._token_list.append(separator_token)

        if space_after_separator and not separator_token.is_whitespace:
            self._token_list.append(Deb822WhitespaceToken(' '))

    def replace(self, orig_value: str, new_value: str) -> None:
        """Replace the first instance of a value with another"""
        for node in self._token_list.iter_nodes():
            if node.value.text == orig_value:
                node.value = self._value_factory(new_value)
                self._changed = True
                break
        else:
            raise ValueError("list.replace(x, y): x not in list")

    def remove(self, value: str) -> None:

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

        first_value_on_lhs: Optional[_LinkedListNode[Deb822Token]] = None
        first_value_on_rhs: Optional[_LinkedListNode[Deb822Token]] = None
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
        _LinkedListNode.link_nodes(first_remain_lhs, first_remain_rhs)

    def append(self, value: str) -> None:
        vt = self._value_factory(value)
        self.append_value(vt)

    def append_value(self, vt: VT) -> None:
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

    def _previous_is_newline(self) -> bool:
        tail = self._token_list.tail
        return tail is not None and tail.text.endswith("\n")

    def append_newline(self) -> None:
        if self._previous_is_newline():
            raise ValueError("Cannot add a newline after a token that ends on a newline")
        self._token_list.append(Deb822NewlineAfterValueToken())

    def append_comment(self, comment_text: str) -> None:
        tail = self._token_list.tail
        if tail is None or not tail.text.endswith('\n'):
            self.append_newline()
        comment_token = Deb822CommentToken(_format_comment(comment_text))
        self._token_list.append(comment_token)

    def _append_continuation_line_token_if_necessary(self) -> None:
        tail = self._token_list.tail
        if tail is not None and tail.text.endswith("\n"):
            self._token_list.append(Deb822ValueContinuationToken())

    def reformat_when_finished(self) -> None:
        self._enable_reformatting()
        self._changed = True

    def _enable_reformatting(self) -> None:
        self._format_one_value_per_line = True
        self._format_with_leading_whitespace_matching_field_length = True
        self._format_trailing_separator_after_last_element = True
        self._format_preserve_original_formatting = False

    def no_reformatting_when_finished(self) -> None:
        self._format_one_value_per_line = False
        self._format_with_leading_whitespace_matching_field_length = False
        self._format_trailing_separator_after_last_element = False
        self._format_preserve_original_formatting = True

    def _generate_reformatted_field_content(self) -> str:
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
        token_iter: Iterator[Deb822Token] = (t for t in self._token_list
                                             if t.is_comment or isinstance(t, vtype))

        def _token_iter() -> Iterable[str]:
            first_token: Optional[Deb822Token] = next(token_iter, None)
            assert first_token is not None and isinstance(first_token, vtype)
            # Leading space after ":"
            yield ' '
            # Not sure why mypy concludes that first_token must be "<nothing>"
            # when it is clearly typed as a Deb822Token plus it would have
            # passed an "assert isinstance" check too.
            yield first_token.text  # type: ignore
            pending_separator = True
            ended_on_a_newline = False
            last_token: Deb822Token = first_token
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

    def _generate_field_content(self) -> str:
        return "".join(t.text for t in self._token_list)

    def _update_field(self) -> None:
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
            raise ValueError(f"Syntax error in new field value for {field_name}")
        paragraph = next(iter(deb822_file.paragraphs))
        assert isinstance(paragraph, Deb822ValidParagraphElement)
        new_kvpair_element = paragraph[field_name]
        kvpair_element.value_element = new_kvpair_element.value_element
        self._changed = False


class Interpretation(Generic[T]):

    def interpret(self, kvpair_element: 'Deb822KeyValuePairElement') -> T:
        raise NotImplementedError  # pragma: no cover


class LineByLineBasedInterpretation(Interpretation[T]):

    def __init__(self,
                 tokenizer: Callable[[str], Iterable['Deb822Token']]):
        super().__init__()
        self._tokenizer = tokenizer

    def _high_level_interpretation(self, kvpair_element: 'Deb822KeyValuePairElement',
                                   token_list: List['Deb822Token']) -> T:
        raise NotImplementedError  # pragma: no cover

    def interpret(self, kvpair_element: 'Deb822KeyValuePairElement') -> T:
        code = self._tokenizer
        token_list: List['Deb822Token'] = []
        for vl in kvpair_element.value_element.value_lines:
            content_text = vl.convert_content_to_text()

            value_parts = list(_check_line_is_covered(len(content_text),
                                                      content_text,
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


def _tokenizer_to_value_factory(tokenizer: Callable[[str], Iterable['Deb822Token']],
                                vtype: typing.Type[VT],
                                ) -> Callable[[str], VT]:
    def _value_factory(v: str) -> VT:
        if v == '':
            raise ValueError("The empty string is not a value")
        token_iter = iter(tokenizer(v))
        t1: Optional[Union[Deb822Token, VT]] = next(token_iter, None)
        t2 = next(token_iter, None)
        assert t1 is not None, f'Bad tokenizer - it returned None (or no tokens) for "{v}"'
        if t2 is not None:
            raise ValueError(f'The input "{v}" should have been exactly one token,'
                             ' but the tokenizer provided at least two.  This can'
                             ' happen with unnecessary leading/trailing whitespace'
                             ' or including commas the value for a comma list.')
        if not isinstance(t1, vtype):
            raise ValueError(f'The input "{v}" should have produced a token of type'
                             f' {vtype.__name__}, but instead it produced {t1}.')

        assert len(t1.text) == len(v), "Bad tokenizer - the token did not cover the input text" \
                                       f" exactly ({len(t1.text)} != {len(v)}"
        return t1

    return _value_factory


class ListInterpretation(LineByLineBasedInterpretation[Deb822ParsedTokenList[VT, ST]]):

    def __init__(self,
                 tokenizer: Callable[[str], Iterable['Deb822Token']],
                 vtype: typing.Type[VT],
                 stype: typing.Type[ST],
                 default_separator_factory: Callable[[], ST],
                 ) -> None:
        super().__init__(tokenizer)
        self._vtype = vtype
        self._stype = stype
        self._default_separator_factory = default_separator_factory

    def _high_level_interpretation(self,
                                   kvpair_element: 'Deb822KeyValuePairElement',
                                   token_list: List['Deb822Token'],
                                   ) -> Deb822ParsedTokenList[VT, ST]:
        return Deb822ParsedTokenList(
            kvpair_element,
            token_list,
            self._vtype,
            self._stype,
            self._tokenizer,
            self._default_separator_factory,
        )


def _whitespace_separated_list_of_tokens(v: str) -> 'Iterable[Deb822Token]':
    assert not _RE_WHITESPACE_LINE.match(v)
    for match in _RE_WHITESPACE_SEPARATED_WORD_LIST.finditer(v):
        space_before, word, space_after = match.groups()
        if space_before:
            yield Deb822SpaceSeparatorToken(sys.intern(space_before))
        yield Deb822ValueToken(word)
        if space_after:
            yield Deb822SpaceSeparatorToken(sys.intern(space_after))


def _comma_separated_list_of_tokens(v: str) -> 'Iterable[Deb822Token]':
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


class Deb822Token:
    """A token is an atomic syntactical element from a deb822 file

    A file is parsed into a series of tokens.  If these tokens are converted to
    text in exactly the same order, you get exactly the same file - bit-for-bit.
    Accordingly ever bit of text in a file must be assigned to exactly one
    Deb822Token.
    """

    __slots__ = ('_text', '_hash', '_parent_element', '__weakref__')

    def __init__(self, text: str) -> None:
        if text == '':  # pragma: no cover
            raise ValueError("Tokens must have content")
        self._text: str = text
        self._hash: Optional[int] = None
        self._parent_element: Optional[ReferenceType['Deb822Element']] = None
        if '\n' in self._text:
            is_single_line_token = False
            if self.is_comment or isinstance(self, Deb822ErrorToken):
                is_single_line_token = True
            if not is_single_line_token and not self.is_whitespace:
                raise ValueError("Only whitespace, error and comment tokens may contain newlines")
            if not self.text.endswith("\n"):
                raise ValueError("Tokens containing whitespace must end on a newline")
            if is_single_line_token and '\n' in self.text[:-1]:
                raise ValueError("Comments and error tokens must not contain embedded newlines"
                                 " (only end on one)")

    def __repr__(self) -> str:
        if self._text != "":
            return "{clsname}('{text}')".format(clsname=self.__class__.__name__,
                                                text=self._text.replace('\n', '\\n')
                                                )
        return self.__class__.__name__

    @property
    def is_whitespace(self) -> bool:
        return False

    @property
    def is_comment(self) -> bool:
        return False

    @property
    def text(self) -> str:
        return self._text

    @property
    def parent_element(self) -> 'Optional[Deb822Element]':
        return _resolve_ref(self._parent_element)

    @parent_element.setter
    def parent_element(self, new_parent: 'Optional[Deb822Element]') -> None:
        self._parent_element = weakref.ref(new_parent) if new_parent is not None else None

    def clear_parent_if_parent(self, parent: 'Deb822Element') -> None:
        if parent is self.parent_element:
            self._parent_element = None


class Deb822WhitespaceToken(Deb822Token):
    """The token is a kind of whitespace.

    Some whitespace tokens are critical for the format (such as the Deb822ValueContinuationToken,
    spaces that separate words in list separated by spaces or newlines), while other whitespace
    tokens are truly insignificant (space before a newline, space after a comma in a comma
    list, etc.).
    """

    @property
    def is_whitespace(self) -> bool:
        return True


class Deb822SemanticallySignificantWhiteSpace(Deb822WhitespaceToken):
    """Whitespace that (if removed) would change the meaning of the file (or cause syntax errors)"""


class Deb822NewlineAfterValueToken(Deb822SemanticallySignificantWhiteSpace):
    """The newline after a value token.

    If not followed by a continuation token, this also marks the end of the field.
    """

    def __init__(self) -> None:
        super().__init__('\n')


class Deb822ValueContinuationToken(Deb822SemanticallySignificantWhiteSpace):
    """The whitespace denoting a value spanning an additional line (the first space on a line)"""

    def __init__(self) -> None:
        super().__init__(' ')


class Deb822SpaceSeparatorToken(Deb822SemanticallySignificantWhiteSpace):
    """Whitespace between values in a space list (e.g. "Architectures")"""


class Deb822ErrorToken(Deb822Token):
    """Token that represents a syntactical error"""


class Deb822CommentToken(Deb822Token):

    @property
    def is_comment(self) -> bool:
        return True


class Deb822FieldNameToken(Deb822Token):

    def __init__(self, text: str) -> None:
        if not isinstance(text, _strI):
            text = _strI(sys.intern(text))
        super().__init__(text)

    @property
    def text(self) -> _strI:
        return typing.cast('_strI', self._text)


# The colon after the field name, parenthesis, etc.
class Deb822SeparatorToken(Deb822Token):
    pass


class Deb822FieldSeparatorToken(Deb822Token):

    def __init__(self) -> None:
        super().__init__(':')


class Deb822CommaToken(Deb822SeparatorToken):
    """Used by the comma-separated list value parsers to denote a comma between two value tokens."""

    def __init__(self) -> None:
        super().__init__(',')


class Deb822PipeToken(Deb822SeparatorToken):
    """Used in some dependency fields as OR relation"""

    def __init__(self) -> None:
        super().__init__('|')


class Deb822ValueToken(Deb822Token):
    """A field value can be split into multi "Deb822ValueToken"s (as well as separator tokens)"""


class Deb822ValueDependencyToken(Deb822Token):
    """Package name, architecture name, a version number, or a profile name in a dependency field"""


class Deb822ValueDependencyVersionRelationOperatorToken(Deb822Token):
    pass


class Deb822Element:
    """Composite elements (consists of 1 or more tokens)"""

    __slots__ = ('_parent_element', '__weakref__')

    def __init__(self) -> None:
        self._parent_element: Optional[ReferenceType['Deb822Element']] = None

    def iter_parts(self) -> Iterable[TokenOrElement]:
        raise NotImplementedError  # pragma: no cover

    def iter_parts_of_type(self, only_element_or_token_type: 'typing.Type[E]') -> 'Iterable[E]':
        for part in self.iter_parts():
            if isinstance(part, only_element_or_token_type):
                yield part

    def iter_tokens(self) -> Iterable[Deb822Token]:
        for part in self.iter_parts():
            if isinstance(part, Deb822Element):
                yield from part.iter_tokens()
            else:
                yield part

    def iter_recurse(self, *,
                     only_element_or_token_type: 'Optional[typing.Type[E]]' = None
                     ) -> 'Iterable[E]':
        for part in self.iter_parts():
            if only_element_or_token_type is None or isinstance(part, only_element_or_token_type):
                yield typing.cast('E', part)
            if isinstance(part, Deb822Element):
                yield from part.iter_recurse(only_element_or_token_type=only_element_or_token_type)

    @property
    def parent_element(self) -> 'Optional[Deb822Element]':
        return _resolve_ref(self._parent_element)

    @parent_element.setter
    def parent_element(self, new_parent: 'Optional[Deb822Element]') -> None:
        self._parent_element = weakref.ref(new_parent) if new_parent is not None else None

    def _init_parent_of_parts(self) -> None:
        for part in self.iter_parts():
            part.parent_element = self

    # Deliberately not a "text" property, to signal that it is not necessary cheap.
    def convert_to_text(self) -> str:
        return "".join(t.text for t in self.iter_tokens())

    def clear_parent_if_parent(self, parent: 'Deb822Element') -> None:
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

    def __init__(self, parts: List[TokenOrElement]):
        super().__init__()
        self._parts = parts
        self._init_parent_of_parts()

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from self._parts


class Deb822ValueLineElement(Deb822Element):
    """Consists of one "line" of a value"""

    __slots__ = ('_comment_element', '_continuation_line_token', '_leading_whitespace_token',
                 '_value_tokens', '_trailing_whitespace_token', '_newline_token')

    def __init__(self,
                 comment_element: 'Optional[Deb822CommentElement]',
                 continuation_line_token: 'Optional[Deb822ValueContinuationToken]',
                 leading_whitespace_token: 'Optional[Deb822WhitespaceToken]',
                 value_parts: 'List[TokenOrElement]',
                 trailing_whitespace_token: 'Optional[Deb822WhitespaceToken]',
                 # only optional if it is the last line of the file and the file does not
                 # end with a newline.
                 newline_token: 'Optional[Deb822WhitespaceToken]',
                 ):
        super().__init__()
        if comment_element is not None and continuation_line_token is None:
            raise ValueError("Only continuation lines can have comments")
        self._comment_element: 'Optional[Deb822CommentElement]' = comment_element
        self._continuation_line_token = continuation_line_token
        self._leading_whitespace_token: 'Optional[Deb822WhitespaceToken]' = leading_whitespace_token
        self._value_tokens: 'List[TokenOrElement]' = value_parts
        self._trailing_whitespace_token = trailing_whitespace_token
        self._newline_token: 'Optional[Deb822WhitespaceToken]' = newline_token
        self._init_parent_of_parts()

    @property
    def comment_element(self) -> 'Optional[Deb822CommentElement]':
        return self._comment_element

    @property
    def continuation_line_token(self) -> 'Optional[Deb822ValueContinuationToken]':
        return self._continuation_line_token

    @property
    def newline_token(self) -> 'Optional[Deb822WhitespaceToken]':
        return self._newline_token

    def add_newline_if_missing(self) -> None:
        if self._newline_token is None:
            self._newline_token = Deb822NewlineAfterValueToken()

    def _iter_content_parts(self) -> Iterable[TokenOrElement]:
        if self._leading_whitespace_token:
            yield self._leading_whitespace_token
        yield from self._value_tokens
        if self._trailing_whitespace_token:
            yield self._trailing_whitespace_token

    def _iter_content_tokens(self) -> Iterable[Deb822Token]:
        for part in self._iter_content_parts():
            if isinstance(part, Deb822Element):
                yield from part.iter_tokens()
            else:
                yield part

    def convert_content_to_text(self) -> str:
        if len(self._value_tokens) == 1 \
                and not self._leading_whitespace_token \
                and not self._trailing_whitespace_token \
                and isinstance(self._value_tokens[0], Deb822Token):
            # By default, we get a single value spanning the entire line
            # (minus continuation line and newline but we are supposed to
            # exclude those)
            return self._value_tokens[0].text

        return "".join(t.text for t in self._iter_content_tokens())

    def iter_parts(self) -> Iterable[TokenOrElement]:
        if self._comment_element:
            yield self._comment_element
        if self._continuation_line_token:
            yield self._continuation_line_token
        yield from self._iter_content_parts()
        if self._newline_token:
            yield self._newline_token


class Deb822ValueElement(Deb822Element):
    __slots__ = ('_value_entry_elements',)

    def __init__(self, value_entry_elements: 'List[Deb822ValueLineElement]') -> None:
        super().__init__()
        self._value_entry_elements: 'List[Deb822ValueLineElement]' = value_entry_elements
        self._init_parent_of_parts()

    @property
    def value_lines(self) -> 'List[Deb822ValueLineElement]':
        """Read-only list of value entries"""
        return self._value_entry_elements

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from self._value_entry_elements

    def add_final_newline_if_missing(self) -> None:
        if self._value_entry_elements:
            self._value_entry_elements[-1].add_newline_if_missing()


class Deb822CommentElement(Deb822Element):
    __slots__ = ('_comment_tokens',)

    def __init__(self, comment_tokens: List[Deb822CommentToken]) -> None:
        super().__init__()
        self._comment_tokens: List[Deb822CommentToken] = comment_tokens
        if not comment_tokens:  # pragma: no cover
            raise ValueError("Comment elements must have at least one comment token")
        self._init_parent_of_parts()

    def __len__(self) -> int:
        return len(self._comment_tokens)

    def __getitem__(self, item: int) -> Deb822CommentToken:
        return self._comment_tokens[item]

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from self._comment_tokens


class Deb822KeyValuePairElement(Deb822Element):
    __slots__ = ('_comment_element', '_field_token', '_separator_token', '_value_element')

    def __init__(self,
                 comment_element: 'Optional[Deb822CommentElement]',
                 field_token: 'Deb822FieldNameToken',
                 separator_token: 'Deb822FieldSeparatorToken',
                 value_element: 'Deb822ValueElement',
                 ) -> None:
        super().__init__()
        self._comment_element: 'Optional[Deb822CommentElement]' = comment_element
        self._field_token: 'Deb822FieldNameToken' = field_token
        self._separator_token: 'Deb822FieldSeparatorToken' = separator_token
        self._value_element: 'Deb822ValueElement' = value_element
        self._init_parent_of_parts()

    @property
    def field_name(self) -> _strI:
        return self.field_token.text

    @property
    def field_token(self) -> Deb822FieldNameToken:
        return self._field_token

    @property
    def value_element(self) -> Deb822ValueElement:
        return self._value_element

    @value_element.setter
    def value_element(self, new_value: Deb822ValueElement) -> None:
        self._value_element.clear_parent_if_parent(self)
        self._value_element = new_value
        new_value.parent_element = self

    def interpret_as(self, interpreter: Interpretation[T]) -> T:
        return interpreter.interpret(self)

    @property
    def comment_element(self) -> Optional[Deb822CommentElement]:
        return self._comment_element

    @comment_element.setter
    def comment_element(self, value: Optional[Deb822CommentElement]) -> None:
        if value is not None:
            if not value[-1].text.endswith("\n"):
                raise ValueError("Field comments must end with a newline")
        if self._comment_element:
            self._comment_element.clear_parent_if_parent(self)
        if value is not None:
            value.parent_element = self
        self._comment_element = value

    def iter_parts(self) -> Iterable[TokenOrElement]:
        if self._comment_element:
            yield self._comment_element
        yield self._field_token
        yield self._separator_token
        yield self._value_element


def _format_comment(c: str) -> str:
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


def _unpack_key(item: ParagraphKey,
                resolve_field_name: bool = False,
                raise_if_indexed: bool = False
                ) -> typing.Tuple[ParagraphKeyBase, Optional[int]]:
    index: Optional[int]
    key: ParagraphKeyBase
    if isinstance(item, tuple):
        key, index = item
        if raise_if_indexed:
            # Fudge "(key, 0)" into a "key" callers to defensively support
            # both paragraph styles with the same key.
            if index != 0:
                raise KeyError(f'Cannot resolve key "{key}" with index {index}.'
                               f' The key is not indexed')
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


def _convert_value_lines_to_lines(value_lines: Iterable[Deb822ValueLineElement],
                                  strip_comments: bool
                                  ) -> Iterable[str]:
    if not strip_comments:
        yield from (v.convert_to_text() for v in value_lines)
    else:
        for element in value_lines:
            yield ''.join(x.text for x in element.iter_tokens()
                          if not x.is_comment)


class Deb822DictishParagraphWrapper:

    def __init__(self,
                 paragraph: 'Deb822ParagraphElement',
                 *,
                 discard_comments_on_read: bool = True,
                 auto_map_initial_line_whitespace: bool = True,
                 auto_resolve_ambiguous_fields: bool = False,
                 preserve_field_comments_on_field_updates: bool = True
                 ):
        self._paragraph = paragraph
        self.discard_comments_on_read = discard_comments_on_read
        self.auto_map_initial_line_whitespace = auto_map_initial_line_whitespace
        self.auto_resolve_ambiguous_fields = auto_resolve_ambiguous_fields
        self.preserve_field_comments_on_field_updates = preserve_field_comments_on_field_updates

    def __contains__(self, item: str) -> bool:
        return item in self._paragraph

    def _convert_value_to_str(self, kvpair_element: Deb822KeyValuePairElement) -> str:
        value_element = kvpair_element.value_element
        value_entries = value_element.value_lines
        if len(value_entries) == 1:
            # Special case single line entry (e.g. "Package: foo") as they never
            # have comments and we can do some parts more efficient.
            value_entry = value_entries[0]
            t = value_entry.convert_to_text()
            if self.auto_map_initial_line_whitespace:
                t = t.strip()
            return t

        if not self.auto_map_initial_line_whitespace and not self.discard_comments_on_read:
            # No rewrite necessary.
            return value_element.convert_to_text()

        converter = _convert_value_lines_to_lines(value_entries,
                                                  self.discard_comments_on_read,
                                                  )

        auto_map_space = self.auto_map_initial_line_whitespace

        # Because we know there are more than one line, we can unconditionally inject
        # the newline after the first line
        return ''.join(line.strip() + "\n" if auto_map_space and i == 1 else line
                       for i, line in enumerate(converter, start=1)
                       )

    def get(self, item: str) -> Optional[str]:
        if self.auto_resolve_ambiguous_fields:
            v = self._paragraph.get((item, 0))
        else:
            v = self._paragraph.get(item)
        if v is None:
            return None
        return self._convert_value_to_str(v)

    def __getitem__(self, item: str) -> str:
        if self.auto_resolve_ambiguous_fields:
            v = self._paragraph[(item, 0)]
        else:
            v = self._paragraph[item]
        return self._convert_value_to_str(v)

    def __setitem__(self, field_name: str, value: str) -> None:
        keep_comments: Optional[bool] = self.preserve_field_comments_on_field_updates
        comment = None
        if keep_comments and self.auto_resolve_ambiguous_fields:
            # For ambiguous fields, we have to resolve the original field as
            # the set_field_* methods do not cope with ambiguous fields.  This
            # means we might as well clear the keep_comments flag as we have
            # resolved the comment.
            keep_comments = None
            orig_kvpair = self._paragraph.get((field_name, 0))
            if orig_kvpair is not None:
                comment = orig_kvpair.comment_element

        if self.auto_map_initial_line_whitespace:
            if '\n' not in value and not value[0].isspace():
                self._paragraph.set_field_to_simple_value(
                    field_name,
                    value,
                    preserve_original_field_comment=keep_comments,
                    field_comment=comment,
                )
                return
        if not value.endswith("\n"):
            raise ValueError("Values must end with a newline (or be single line"
                             " values and use the auto whitespace mapping feature)")
        self._paragraph.set_field_from_raw_string(
            field_name,
            value,
            preserve_original_field_comment=keep_comments,
            field_comment=comment,
        )

    def __delitem__(self, item: str) -> None:
        del self._paragraph[item]


class Deb822ParagraphElement(Deb822Element, ABC):

    @classmethod
    def from_kvpairs(cls, kvpair_elements: List[Deb822KeyValuePairElement]
                     ) -> 'Deb822ParagraphElement':
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

    def as_dict_view(self,
                     *,
                     discard_comments_on_read: bool = True,
                     auto_map_initial_line_whitespace: bool = True,
                     auto_resolve_ambiguous_fields: bool = False,
                     preserve_field_comments_on_field_updates: bool = True,
                     ) -> Deb822DictishParagraphWrapper:
        r"""Provide a Dict[str, str] like-view of this paragraph

        This method returns a dict-like object representing this paragraph,
        which attempts to hide most of the complexity of the
        Deb822ParagraphElement at the expense of flexibility.

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... # Field comment (because it becomes just before a field)
            ... Depends: libfoo,
            ... # Inline comment (associated with the next line)
            ...          libbar,
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> paragraph = next(iter(dfile.paragraphs))
            >>> dictview = paragraph.as_dict_view()
            >>> # With the defaults, you only deal with the semantic values
            >>> # - no leading or trailing whitespace on the first part of the value
            >>> dictview["Package"]
            'foo'
            >>> # - no inline comments in multiline values (but whitespace will be present
            >>> #   subsequent lines.)
            >>> print(dictview["Depends"], end='')
            libfoo,
                     libbar,
            >>> dictview['Foo'] = 'bar'
            >>> dictview.get('Foo')
            'bar'
            >>> dictview.get('Unknown-Field') is None
            True
            >>> # But you get asymmetric behaviour with set vs. get
            >>> dictview['Foo'] = ' bar\n'
            >>> dictview['Foo']
            'bar'
            >>> dictview['Bar'] = '     bar\n#Comment\n another value\n'
            >>> dictview['Bar']
            'bar\n another value\n'
            >>> # The comment is present (in case you where wondering)
            >>> print(paragraph['Bar'].convert_to_text(), end='')
            Bar:     bar
            #Comment
             another value
            >>> # On the other hand, you can choose to see the values as they are
            >>> # - We will just reset the paragraph as a "nothing up my sleeve"
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> paragraph = next(iter(dfile.paragraphs))
            >>> dictview = paragraph.as_dict_view()
            >>> nonstd_dictview = paragraph.as_dict_view(
            ...     discard_comments_on_read=False,
            ...     auto_map_initial_line_whitespace=False,
            ...     # For paragraphs with duplicate fields, this makes you always get the first
            ...     # field
            ...     auto_resolve_ambiguous_fields=True,
            ... )
            >>> # Because we have reset the state, Foo and Bar are no longer there.
            >>> 'Bar' not in dictview and 'Foo' not in dictview
            True
            >>> # We can now see the comments (discard_comments_on_read=False)
            >>> print(nonstd_dictview["Depends"], end="")
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
            >>> paragraph['Baz'].convert_to_text()
            'Baz:foo\n'
            >>> # But because they are views, changes performed via one view is visible in the other
            >>> dictview['Foo']
            'bar'
            >>> 'Baz' in dictview and nonstd_dictview.get('Baz') is not None
            True
            >>> # Deletion also works
            >>> del dictview['Baz']
            >>> 'Baz' not in dictview and nonstd_dictview.get('Baz') is None
            True


        :param discard_comments_on_read: When getting a field value from the dict,
          this parameter decides how in-line comments are handled.
        :param auto_map_initial_line_whitespace:
        :param preserve_field_comments_on_field_updates: Whether to preserve the field
          comments when mutating the field.
        :param auto_resolve_ambiguous_fields:
        """
        return Deb822DictishParagraphWrapper(
            self,
            discard_comments_on_read=discard_comments_on_read,
            auto_map_initial_line_whitespace=auto_map_initial_line_whitespace,
            auto_resolve_ambiguous_fields=auto_resolve_ambiguous_fields,
            preserve_field_comments_on_field_updates=preserve_field_comments_on_field_updates,
        )

    def __contains__(self, item: ParagraphKey) -> bool:
        raise NotImplementedError  # pragma: no cover

    def __getitem__(self, item: ParagraphKey) -> Deb822KeyValuePairElement:
        raise NotImplementedError  # pragma: no cover

    def __setitem__(self, key: ParagraphKey, value: Deb822KeyValuePairElement) -> None:
        raise NotImplementedError  # pragma: no cover

    def __delitem__(self, key: Union[Deb822FieldNameToken, str]) -> None:
        raise NotImplementedError  # pragma: no cover

    def get(self, key: ParagraphKey) -> Optional[Deb822KeyValuePairElement]:
        raise NotImplementedError  # pragma: no cover

    def sort_fields(self, key: Optional[Callable[[str], Any]] = None) -> None:
        raise NotImplementedError  # pragma: no cover

    def set_field_to_simple_value(self, field_name: str, simple_value: str, *,
                                  preserve_original_field_comment: Optional[bool] = None,
                                  field_comment: Optional[Commentish] = None,
                                  ) -> None:
        r"""Sets a field in this paragraph to a simple "word" or "phrase"

        This is suitable for "simple" fields like "Package".  Example:

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> p = next(iter(dfile.paragraphs))
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

        :param field_name: Name of the field to set.  If the paragraph already
          contains the field, then it will be replaced.  If the field exists,
          then it will preserve its order in the paragraph.  Otherwise, it is
          added to the end of the paragraph.
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
            field_name,
            raw_value,
            preserve_original_field_comment=preserve_original_field_comment,
            field_comment=field_comment,
        )

    def set_field_from_raw_string(self, field_name: str, raw_string_value: str, *,
                                  preserve_original_field_comment: Optional[bool] = None,
                                  field_comment: Optional[Commentish] = None,
                                  ) -> None:
        """Sets a field in this paragraph to a given text value

        Example usage:

            >>> example_deb822_paragraph = '''
            ... Package: foo
            ... '''
            >>> dfile = parse_deb822_file(example_deb822_paragraph.splitlines(keepends=True))
            >>> p = next(iter(dfile.paragraphs))
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

        :param field_name: Name of the field to set.  If the paragraph already
          contains the field, then it will be replaced.  Otherwise, it is
          added to the end of the paragraph.
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
          paramter is omitted.
        :param field_comment: If not None, add or replace the comment for
          the field.  Each string in the in the list will become one comment
          line (insered directly before the field name). Will appear in the
          same order as they do in the list.

          If you want complete control over the formatting of the comments,
          then ensure that each line start with "#" and end with "\n" before
          the call.  Otherwise, leading/trailing whitespace is normalized
          and the missing "#"/"\n" character is inserted.
        """

        new_content: List[str] = []
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

        raw = ":".join((field_name, raw_string_value))
        raw_lines = raw.splitlines(keepends=True)
        for i, line in enumerate(raw_lines, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"Line {i} in new value was missing trailing newline")
            if i != 1 and line[0] not in (' ', '#'):
                raise ValueError(f'Line {i} in new value was invalid.  It must either start'
                                 ' with " " space (continuation line) or "#" (comment line).'
                                 f' The line started with "{line[0]}"')
        if len(raw_lines) > 1 and raw_lines[-1].startswith('#'):
            raise ValueError('The last line in a value field cannot be a comment')
        new_content.extend(raw_lines)
        # As absurd as it might seem, it is easier to just use the parser to
        # construct the AST correctly
        deb822_file = parse_deb822_file(iter(new_content))
        error_token = deb822_file.find_first_error_element()
        if error_token:
            raise ValueError(f"Syntax error in new field value for {field_name}")
        paragraph = next(iter(deb822_file.paragraphs))
        assert isinstance(paragraph, Deb822ValidParagraphElement)
        value = paragraph[field_name]
        if preserve_original_field_comment:
            original = self.get(value.field_name)
            if original:
                value.comment_element = original.comment_element
                original.comment_element = None
        elif field_comment is not None:
            value.comment_element = field_comment
        self[value.field_name] = value


class Deb822ValidParagraphElement(Deb822ParagraphElement):
    """Paragraph implementation optimized for valid deb822 files

    When there are no duplicated fields, we can use simpler and faster
    datastructures for common operations.
    """

    def __init__(self, kvpair_elements: List[Deb822KeyValuePairElement],
                 kvpair_order: OrderedSet
                 ) -> None:
        super().__init__()
        self._kvpair_elements = {kv.field_name: kv for kv in kvpair_elements}
        self._kvpair_order = kvpair_order
        self._init_parent_of_parts()

    def __contains__(self, item: ParagraphKey) -> bool:
        key, _ = _unpack_key(item, resolve_field_name=True, raise_if_indexed=True)
        key = typing.cast('_strI', key)
        return key in self._kvpair_elements

    def __getitem__(self, item: ParagraphKey) -> Deb822KeyValuePairElement:
        key, _ = _unpack_key(item, resolve_field_name=True, raise_if_indexed=True)
        key = typing.cast('_strI', key)
        return self._kvpair_elements[key]

    def __setitem__(self, key: ParagraphKey,
                    value: Deb822KeyValuePairElement) -> None:
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

    def __delitem__(self, key: Union[Deb822FieldNameToken, str]) -> None:
        key, _ = _unpack_key(key, resolve_field_name=True, raise_if_indexed=True)
        key = typing.cast('_strI', key)
        del self._kvpair_elements[key]

    def get(self, key: ParagraphKey) -> Optional[Deb822KeyValuePairElement]:
        key, _ = _unpack_key(key, resolve_field_name=True, raise_if_indexed=True)
        key = typing.cast('_strI', key)
        return self._kvpair_elements.get(key)

    def sort_fields(self, key: Optional[Callable[[str], Any]] = None) -> None:
        for last_field_name in reversed(self._kvpair_order):
            last_kvpair = self._kvpair_elements[typing.cast('_strI', last_field_name)]
            last_kvpair.value_element.add_final_newline_if_missing()
            break

        self._kvpair_order = OrderedSet(sorted(self._kvpair_order, key=key))

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from (self._kvpair_elements[x]
                    for x in typing.cast('Iterable[_strI]', self._kvpair_order))


class Deb822InvalidParagraphElement(Deb822ParagraphElement):

    def __init__(self, kvpair_elements: List[Deb822KeyValuePairElement]) -> None:
        super().__init__()
        self._kvpair_order: _LinkedList[Deb822KeyValuePairElement] = _LinkedList()
        self._kvpair_elements: Dict[_strI, List[_LinkedListNode[Deb822KeyValuePairElement]]] = {}
        self._init_kvpair_fields(kvpair_elements)
        self._init_parent_of_parts()

    def _init_kvpair_fields(self, kvpairs: Iterable[Deb822KeyValuePairElement]) -> None:
        assert not self._kvpair_order
        assert not self._kvpair_elements
        for kv in kvpairs:
            field_name = kv.field_name
            node = self._kvpair_order.append(kv)
            if field_name not in self._kvpair_elements:
                self._kvpair_elements[field_name] = [node]
            else:
                self._kvpair_elements[field_name].append(node)

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from self._kvpair_order

    def _get_item(self, item: ParagraphKey,
                  use_get: bool = False) -> Optional[Deb822KeyValuePairElement]:
        name_token: Optional[Deb822FieldNameToken]
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
                    # if we are given a name token, then it is non-ambiguous if we have exactly
                    # that name token in our list of nodes.  It will be an O(n) lookup but we
                    # probably do not have that many duplicate fields (and even if do, it is not
                    # exactly a valid file, so there little reason to optimize for it)
                    for node in res:
                        if name_token is node.value.field_token:
                            return node.value

                raise AmbiguousDeb822FieldKeyError(f"Ambiguous key {key} - the field appears "
                                                   f"{len(res)} times. Use ({key}, index) to"
                                                   " denote which instance of the field you want."
                                                   f" (Index can be 0..{len(res) - 1} or e.g. -1 to"
                                                   " denote the last field)")
            index = 0
        return res[index].value

    def __contains__(self, item: ParagraphKey) -> bool:
        key, _ = _unpack_key(item, resolve_field_name=True)
        key = typing.cast('_strI', key)
        return key in self._kvpair_elements

    def __getitem__(self, item: ParagraphKey) -> Deb822KeyValuePairElement:
        v = self._get_item(item)
        # Primarily as a hint to mypy
        assert v is not None
        return v

    def __setitem__(self, key: ParagraphKey, value: Deb822KeyValuePairElement) -> None:
        key, index = _unpack_key(key)
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
        original_nodes = self._kvpair_elements.get(key)
        if original_nodes is None or not original_nodes:
            if index is not None and index != 0:
                raise KeyError(f"Cannot replace field ({key}, {index}) as the field does not exist"
                               f" in the first place.  Please index-less key or ({key}, 0) if you"
                               " want to add the field.")
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

    def __delitem__(self, key: Union[Deb822FieldNameToken, str]) -> None:
        key, _ = _unpack_key(key, resolve_field_name=True, raise_if_indexed=True)
        key = typing.cast('_strI', key)
        res = self._kvpair_elements[key]
        for node in res:
            node.value.parent_element = None
            self._kvpair_order.remove_node(node)
        del self._kvpair_elements[key]

    def get(self, key: ParagraphKey) -> Optional[Deb822KeyValuePairElement]:
        return self._get_item(key, use_get=True)

    def sort_fields(self, key: Optional[Callable[[str], Any]] = None) -> None:
        actual_key: Callable[[Deb822KeyValuePairElement], Any]
        if key is not None:
            # Work around mypy that cannot seem to shred the Optional notion
            # without this little indirection
            key_impl = key

            def _actual_key(kvpair: Deb822KeyValuePairElement) -> Any:
                return key_impl(kvpair.field_name)

            actual_key = _actual_key
        else:
            actual_key = operator.attrgetter('field_name')
        for last_kvpair in reversed(self._kvpair_order):
            last_kvpair.value_element.add_final_newline_if_missing()
            break

        sorted_kvpair_list = sorted(self._kvpair_order, key=actual_key)
        self._kvpair_order = _LinkedList()
        self._kvpair_elements = {}
        self._init_kvpair_fields(sorted_kvpair_list)


class Deb822FileElement(Deb822Element):
    """Represents the entire deb822 file"""

    def __init__(self, token_and_elements: List[TokenOrElement]) -> None:
        super().__init__()
        self._token_and_elements = token_and_elements
        self._init_parent_of_parts()

    @property
    def is_valid_file(self) -> bool:
        """Returns true if the file is valid

        Invalid elements include error elements (Deb822ErrorElement) but also
        issues such as paragraphs with duplicate fields or "empty" files
        (a valid deb822 file contains at least one paragraph).
        """
        paragraphs = list(self.paragraphs)
        if not paragraphs:
            return False
        if any(p for p in paragraphs if not isinstance(p, Deb822ValidParagraphElement)):
            return False
        return self.find_first_error_element() is None

    def find_first_error_element(self) -> Optional[Deb822ErrorElement]:
        """Returns the first Deb822ErrorElement (or None) in the file"""
        return next(iter(self.iter_recurse(only_element_or_token_type=Deb822ErrorElement)), None)

    @property
    def paragraphs(self) -> Iterable[Deb822ParagraphElement]:
        return self.iter_parts_of_type(Deb822ParagraphElement)

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from self._token_and_elements

    def write_to_fd(self, fd: typing.TextIO) -> None:
        for token in self.iter_tokens():
            fd.write(token.text)


class _BufferingIterator(collections.abc.Iterator[T]):

    def __init__(self, stream: Iterable[T]) -> None:
        self._stream: typing.Iterator[T] = iter(stream)
        self._buffer: collections.deque[T] = collections.deque()
        self._expired: bool = False

    def __next__(self) -> T:
        if self._buffer:
            return self._buffer.popleft()
        if self._expired:
            raise StopIteration
        return next(self._stream)

    def takewhile(self, predicate: Callable[[T], bool]) -> Iterable[T]:
        """Variant of itertools.takewhile except it does not discard the first non-matching token"""
        buffer = self._buffer
        while buffer or self._fill_buffer(5):
            v = buffer[0]
            if predicate(v):
                buffer.popleft()
                yield v
            else:
                break

    def _fill_buffer(self, number: int) -> bool:
        if not self._expired:
            while len(self._buffer) < number:
                try:
                    self._buffer.append(next(self._stream))
                except StopIteration:
                    self._expired = True
                    break
        return bool(self._buffer)

    def peek(self) -> Optional[T]:
        return self.peek_at(1)

    def peek_at(self, tokens_ahead: int) -> Optional[T]:
        self._fill_buffer(tokens_ahead)
        return self._buffer[tokens_ahead - 1] if self._buffer else None

    def peek_many(self, number: int) -> List[T]:
        self._fill_buffer(number)
        return list(self._buffer)


def _check_line_is_covered(line_len: int, line: str, stream: Iterable[TokenOrElement]
                           ) -> Iterable[Deb822Token]:
    # Fail-safe to ensure none of the value parsers incorrectly parse a value.
    covered = 0
    for token_or_element in stream:
        if isinstance(token_or_element, Deb822Element):
            for token in token_or_element.iter_tokens():
                covered += len(token.text)
                yield token
        else:
            token = token_or_element
            covered += len(token.text)
            yield token
    if covered != line_len:
        if covered < line_len:
            raise ValueError(f"Value parser did not fully cover the entire line with tokens ("
                             f'missing range {covered}..{line_len}).  Occurred when parsing'
                             f' "{line}"')
        raise ValueError(f"Value parser emitted tokens for more text than was present?  Should have"
                         f' emitted {line_len} characters, got {covered}. Occurred when parsing'
                         f' "{line}"')


def _tokenize_deb822_file(line_iter: Iterable[str]) -> Iterable[Deb822Token]:
    """Tokenize a deb822 file

    :param line_iter: An iterable of lines (a file open for reading will do)
    """
    current_field_name = None
    field_name_cache: Dict[str, _strI] = {}

    text_stream: _BufferingIterator[str] = _BufferingIterator(line_iter)

    for no, line in enumerate(text_stream, start=1):

        if not line.endswith("\n"):
            # We expect newlines at the end of each line except the last.
            if text_stream.peek() is not None:
                raise ValueError(f"Invalid line iterator: Line {no} did not end on a newline and"
                                 " it is not the last line in the stream!")
            if line == '':
                raise ValueError(f"Line {no} was completely empty.  The tokenizer expects"
                                 " whitespace (including newlines) to be present")
        if _RE_WHITESPACE_LINE.match(line):
            if current_field_name:
                # Blank lines terminate fields
                current_field_name = None

            # If there are multiple whitespace-only lines, we combine them
            # into one token.
            r = list(text_stream.takewhile(lambda x: _RE_WHITESPACE_LINE.match(x) is not None))
            if r:
                line = line + "".join(r)

            # whitespace tokens are likely to have duplicate cases (like
            # single newline tokens), so we intern the strings there.
            yield Deb822WhitespaceToken(sys.intern(line))
            continue

        if line[0] == '#':
            yield Deb822CommentToken(line)
            continue

        if line[0] == ' ':
            if current_field_name is not None:
                # We emit a separate whitespace token for the newline as it makes some
                # things easier later (see _build_value_line)
                if line.endswith('\n'):
                    line = line[1:-1]
                    emit_newline_token = True
                else:
                    line = line[1:]
                    emit_newline_token = False

                yield Deb822ValueContinuationToken()
                yield Deb822ValueToken(line)
                if emit_newline_token:
                    yield Deb822NewlineAfterValueToken()
            else:
                yield Deb822ErrorToken(line)
            continue

        field_line_match = _RE_FIELD_LINE.match(line)
        if field_line_match:
            # The line is a field, which means there is a bit to unpack
            # - note that by definition, leading and trailing whitespace is insignificant
            #   on the value part directly after the field separator
            (field_name, _, space_before, value, space_after) = field_line_match.groups()

            current_field_name = field_name_cache.get(field_name)
            emit_newline_token = False

            if value is None or value == '':
                # If there is no value, then merge the two space elements into space_after
                # as it makes it easier to handle the newline.
                space_after = space_before + space_after if space_after else space_before
                space_before = ''

            if space_after:
                # We emit a separate whitespace token for the newline as it makes some
                # things easier later (see _build_value_line)
                emit_newline_token = space_after.endswith('\n')
                if emit_newline_token:
                    space_after = space_after[:-1]

            if current_field_name is None:
                field_name = sys.intern(field_name)
                current_field_name = _strI(field_name)
                field_name_cache[field_name] = current_field_name

            # We use current_field_name from here as it is a _strI.
            # Delete field_name to avoid accidentally using it and getting bugs
            # that should not happen.
            del field_name

            yield Deb822FieldNameToken(current_field_name)
            yield Deb822FieldSeparatorToken()
            if space_before:
                yield Deb822WhitespaceToken(sys.intern(space_before))
            if value:
                yield Deb822ValueToken(value)
            if space_after:
                yield Deb822WhitespaceToken(sys.intern(space_after))
            if emit_newline_token:
                yield Deb822NewlineAfterValueToken()
        else:
            yield Deb822ErrorToken(line)


_combine_parts_ret_type = Callable[
    [Iterable[Union[TokenOrElement, S]]],
    Iterable[Union[TokenOrElement, R]]
]


def _combine_parts(source_class: typing.Type[S], replacement_class: typing.Type[R],
                   *,
                   constructor: Optional[Callable[[List[S]], R]] = None
                   ) -> _combine_parts_ret_type[S, R]:
    if constructor is None:
        _constructor = typing.cast('Callable[[List[S]], R]', replacement_class)
    else:
        # Force mypy to see that constructor is no longer optional
        _constructor = constructor
    def _impl(token_stream: Iterable[Union[TokenOrElement, S]]
              ) -> Iterable[Union[TokenOrElement, R]]:
        tokens = []
        for token in token_stream:
            if isinstance(token, source_class):
                tokens.append(token)
                continue

            if tokens:
                yield _constructor(list(tokens))
                tokens.clear()
            yield token

        if tokens:
            yield _constructor(tokens)

    return _impl


_combine_error_tokens_into_elements = _combine_parts(Deb822ErrorToken, Deb822ErrorElement)
_combine_comment_tokens_into_elements = _combine_parts(Deb822CommentToken, Deb822CommentElement)
_combine_vl_elements_into_value_elements = _combine_parts(Deb822ValueLineElement,
                                                          Deb822ValueElement)
_combine_kvp_elements_into_paragraphs = _combine_parts(
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


def _non_end_of_line_token(v: TokenOrElement) -> bool:
    # Consume tokens until the newline
    return not isinstance(v, Deb822WhitespaceToken) or v.text != '\n'


def _build_value_line(token_stream: Iterable[Union[TokenOrElement, Deb822CommentElement]]
                      ) -> Iterable[Union[TokenOrElement, Deb822ValueLineElement]]:
    """Parser helper - consumes tokens part of a Deb822ValueEntryElement and turns them into one"""
    buffered_stream = _BufferingIterator(token_stream)

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
    token: Optional[TokenOrElement]

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
                continuation_line_token = typing.cast('Deb822ValueContinuationToken',
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
            eol_token = typing.cast('Deb822WhitespaceToken', next(buffered_stream, None))
            assert eol_token is None or eol_token.text == '\n'
            leading_whitespace = None
            trailing_whitespace = None
            # "Depends:\n foo" would cause tokens_in_value to be empty for the
            # first "value line" (the empty part between ":" and "\n")
            if tokens_in_value:
                # Another special-case, "Depends: \n foo" (i.e. space after colon)
                # should not introduce an IndexError
                if isinstance(tokens_in_value[-1], Deb822WhitespaceToken):
                    trailing_whitespace = typing.cast('Deb822WhitespaceToken',
                                                      tokens_in_value.pop()
                                                      )
                if tokens_in_value and isinstance(tokens_in_value[-1], Deb822WhitespaceToken):
                    leading_whitespace = typing.cast('Deb822WhitespaceToken', tokens_in_value[0])
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


def _build_field_with_value(token_stream: Iterable[Union[TokenOrElement, Deb822ValueElement]]
                            ) -> Iterable[Union[TokenOrElement, Deb822KeyValuePairElement]]:
    buffered_stream = _BufferingIterator(token_stream)
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
                                                typing.cast('Deb822FieldNameToken', field_name),
                                                separator,
                                                value_element,
                                                )
            else:
                # We had a parse error, consume until the newline.
                error_tokens: List[TokenOrElement] = [token_or_element]
                error_tokens.extend(buffered_stream.takewhile(_non_end_of_line_token))
                nl = buffered_stream.peek()
                # Take the newline as well if present
                if nl and isinstance(nl, Deb822NewlineAfterValueToken):
                    error_tokens.append(nl)
                yield Deb822ErrorElement(error_tokens)
        else:
            # Token is not part of a field, emit it as-is
            yield token_or_element


def parse_deb822_file(line_iter: Iterable[str]) -> Deb822FileElement:
    # The order of operations are important here.  As an example,
    # _build_value_line assumes that all comment tokens have been merged
    # into comment elements.  Likewise, _build_field_and_value assumes
    # that value tokens (along with their comments) have been combined
    # into elements.
    tokens: Iterable[TokenOrElement] = _tokenize_deb822_file(line_iter)
    tokens = _combine_comment_tokens_into_elements(tokens)
    tokens = _build_value_line(tokens)
    tokens = _combine_vl_elements_into_value_elements(tokens)
    tokens = _build_field_with_value(tokens)
    tokens = _combine_kvp_elements_into_paragraphs(tokens)
    # Combine any free-floating error tokens into error elements.  We do
    # this last as it enable other parts of the parser to include error
    # tokens in their error elements if they discover something is wrong.
    tokens = _combine_error_tokens_into_elements(tokens)

    return Deb822FileElement(list(tokens))


def _print_ast(ast_tree: Union[Iterable[TokenOrElement], Deb822Element], *,
               end_marker_after: Optional[int] = 5,
               ) -> None:
    """Debugging aid, which can dump a Deb822Element or a list of tokens/elements

    :param ast_tree: Either a Deb822Element or an iterable Deb822Token/Deb822Element entries
      (both types may be mixed in the same iterable, which enable it to dump the
      ast tree at different stages of parse_deb822_file method)
    :param end_marker_after: The dump will add "end of element" markers if a
      given element spans at least this many tokens/elements. Can be disabled
      with by passing None as value. Use 0 for unconditionally marking all
      elements (note that tokens never get an "end of element" marker as they
      are not an elements).

    """
    prefix = None
    if isinstance(ast_tree, Deb822Element):
        ast_tree = [ast_tree]
    stack = [(0, '', iter(ast_tree))]
    current_no = 0
    while stack:
        start_no, name, current_iter = stack[-1]
        for current in current_iter:
            current_no += 1
            if prefix is None:
                prefix = '  ' * len(stack)
            if isinstance(current, Deb822Element):
                stack.append((current_no, current.__class__.__name__, iter(current.iter_parts())))
                print(f"{prefix}{current.__class__.__name__}")
                prefix = None
                break
            print(f"{prefix}{current}")
        else:
            # current_iter is depleted
            stack.pop()
            prefix = None
            if end_marker_after is not None and start_no + end_marker_after <= current_no and name:
                if prefix is None:
                    prefix = '  ' * len(stack)
                print(f"{prefix}# <-- END OF {name}")


if __name__ == "__main__":  # pragma: no cover
    import doctest
    doctest.testmod()
