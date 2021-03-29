import collections
import collections.abc
import re
import sys
import typing
import weakref
from typing import Iterable, List, Union, Dict, Optional, TypeVar, Callable, Any
from weakref import ReferenceType

from .deb822 import _strI, OrderedSet


T = TypeVar('T')
TokenOrElement = Union['Deb822Element', 'Deb822Token']


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


def _resolve_ref(ref: Optional[ReferenceType[T]]) -> Optional[T]:
    return ref() if ref is not None else None


class Deb822Token:
    """A token is an atomic syntactical element from a deb822 file

    They form a long linked list of all tokens in the file.
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

    def iter_parts_of_type(self, only_element_or_token_type: 'typing.Type[T]') -> 'Iterable[T]':
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
                     only_element_or_token_type: 'Optional[typing.Type[TokenOrElement]]' = None
                     ) -> 'Iterable[TokenOrElement]':
        for part in self.iter_parts():
            if only_element_or_token_type is None or isinstance(part, only_element_or_token_type):
                yield part
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
                 value_tokens: 'List[TokenOrElement]',
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
        self._value_tokens: 'List[TokenOrElement]' = value_tokens
        self._trailing_whitespace_token = trailing_whitespace_token
        self._newline_token: 'Optional[Deb822WhitespaceToken]' = newline_token
        self._init_parent_of_parts()

    @property
    def is_continuation_line(self) -> bool:
        return self._continuation_line_token is not None

    def iter_parts(self) -> Iterable[TokenOrElement]:
        if self._comment_element:
            yield self._comment_element
        if self._continuation_line_token:
            yield self._continuation_line_token
        if self._leading_whitespace_token:
            yield self._leading_whitespace_token
        yield from self._value_tokens
        if self._trailing_whitespace_token:
            yield self._trailing_whitespace_token
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


class Deb822ParagraphElement(Deb822Element):

    def __init__(self, kvpair_elements: List[Deb822KeyValuePairElement]) -> None:
        super().__init__()
        self._kvpair_elements = {kv.field_name: kv for kv in kvpair_elements}
        self._kvpair_order = OrderedSet(kv.field_name for kv in kvpair_elements)
        self._init_parent_of_parts()

    def __getitem__(self, item: Union[Deb822FieldNameToken, str]) -> Deb822KeyValuePairElement:
        if isinstance(item, Deb822FieldNameToken):
            item = item.text
        else:
            item = _strI(item)
        return self._kvpair_elements[item]

    def __setitem__(self, key: Union[Deb822FieldNameToken, str],
                    value: Deb822KeyValuePairElement) -> None:
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
        if isinstance(key, Deb822FieldNameToken):
            key = key.text
        else:
            key = _strI(key)
        del self._kvpair_elements[key]

    def get(self, key: Union[Deb822FieldNameToken, str]) -> Optional[Deb822KeyValuePairElement]:
        if isinstance(key, Deb822FieldNameToken):
            key = key.text
        else:
            key = _strI(key)
        return self._kvpair_elements.get(key)

    def set_field_to_simple_value(self, field_name: str, simple_value: str, *,
                                  preserve_original_field_comment: Optional[bool] = None,
                                  field_comment: Optional[List[str]] = None,
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
                                  field_comment: Optional[List[str]] = None,
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
            new_content.extend(_format_comment(x) for x in field_comment)
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
        value = paragraph[field_name]
        if preserve_original_field_comment:
            original = self.get(value.field_name)
            if original:
                value.comment_element = original.comment_element
                original.comment_element = None

        self[value.field_name] = value

    def sort_fields(self, key: Optional[Callable[[str], Any]] = None) -> None:
        self._kvpair_order = OrderedSet(sorted(self._kvpair_order, key=key))

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from (self._kvpair_elements[x]
                    for x in typing.cast('Iterable[_strI]', self._kvpair_order))


class Deb822FileElement(Deb822Element):
    """Represents the entire deb822 file"""

    def __init__(self, token_and_elements: List[TokenOrElement]) -> None:
        super().__init__()
        self._token_and_elements = token_and_elements
        self._init_parent_of_parts()

    @property
    def contains_error_elements(self) -> bool:
        """Returns true if the file contains any error elements"""
        return self.find_first_error_element() is not None

    def find_first_error_element(self) -> Optional[Deb822ErrorElement]:
        """Returns the first Deb822ErrorToken (or None) in the file"""
        v = next((t for t in self.iter_recurse(only_element_or_token_type=Deb822ErrorElement)),
                 None)
        return typing.cast('Optional[Deb822ErrorElement]', v)

    @property
    def paragraphs(self) -> Iterable[Deb822ParagraphElement]:
        return self.iter_parts_of_type(Deb822ParagraphElement)

    def iter_parts(self) -> Iterable[TokenOrElement]:
        yield from self._token_and_elements

    def write_to_fd(self, fd: typing.TextIO) -> None:
        for token in self.iter_tokens():
            fd.write(token.text)


def _treat_everything_as_value(v: str) -> Iterable[Deb822Token]:
    yield Deb822ValueToken(v)


def _whitespace_separated_list_of_tokens(v: str) -> Iterable[Deb822Token]:
    if _RE_WHITESPACE_LINE.match(v):
        raise ValueError("Value lines in Deb822 cannot consist of entirely whitespace")
    for match in _RE_WHITESPACE_SEPARATED_WORD_LIST.finditer(v):
        space_before, word, space_after = match.groups()
        if space_before:
            yield Deb822WhitespaceToken(sys.intern(space_before))
        yield Deb822ValueToken(word)
        if space_after:
            yield Deb822WhitespaceToken(sys.intern(space_after))


def _comma_separated_list_of_tokens(v: str) -> Iterable[Deb822Token]:
    if _RE_WHITESPACE_LINE.match(v):
        raise ValueError("Value lines in Deb822 cannot consist of entirely whitespace")
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


def _check_line_is_covered(line_len: int, line: str, tokens: Iterable[Deb822Token]
                           ) -> Iterable[Deb822Token]:
    # Fail-safe to ensure none of the value parsers incorrectly parse a value.
    covered = 0
    for token in tokens:
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

    value_parser = _treat_everything_as_value

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
                yield from _check_line_is_covered(len(line), line, value_parser(line))
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
                yield from _check_line_is_covered(len(value), value, value_parser(value))
            if space_after:
                yield Deb822WhitespaceToken(sys.intern(space_after))
            if emit_newline_token:
                yield Deb822NewlineAfterValueToken()
        else:
            yield Deb822ErrorToken(line)


S = TypeVar('S', bound=TokenOrElement)
R = TypeVar('R', bound=Deb822Element, covariant=True)

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
_combine_kvp_elements_into_paragraphs = _combine_parts(Deb822KeyValuePairElement,
                                                       Deb822ParagraphElement)


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
