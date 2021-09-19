import re
import sys
from weakref import ReferenceType
import weakref

from debian._deb822_repro._util import resolve_ref, BufferingIterator
from debian.deb822 import _strI

try:
    from typing import Optional, cast, TYPE_CHECKING, Iterable, Union, Dict
except ImportError:
    TYPE_CHECKING = False
    cast = lambda t, v: v

if TYPE_CHECKING:
    from debian._deb822_repro.parsing import Deb822Element


_RE_WHITESPACE_LINE = re.compile(r'^\s+$')

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


class Deb822Token:
    """A token is an atomic syntactical element from a deb822 file

    A file is parsed into a series of tokens.  If these tokens are converted to
    text in exactly the same order, you get exactly the same file - bit-for-bit.
    Accordingly ever bit of text in a file must be assigned to exactly one
    Deb822Token.
    """

    __slots__ = ('_text', '_hash', '_parent_element', '__weakref__')

    def __init__(self, text):
        # type: (str) -> None
        if text == '':  # pragma: no cover
            raise ValueError("Tokens must have content")
        self._text = text  # type: str
        self._hash = None  # type: Optional[int]
        self._parent_element = None  # type: Optional[ReferenceType['Deb822Element']]
        self._verify_token_text()

    def __repr__(self):
        # type: () -> str
        if self._text != "":
            return "{clsname}('{text}')".format(clsname=self.__class__.__name__,
                                                text=self._text.replace('\n', '\\n')
                                                )
        return self.__class__.__name__

    def _verify_token_text(self):
        # type: () -> None
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

    @property
    def is_whitespace(self):
        # type: () -> bool
        return False

    @property
    def is_comment(self):
        # type: () -> bool
        return False

    @property
    def text(self):
        # type: () -> str
        return self._text

    # To support callers that want a simple interface for converting tokens and elements to text
    def convert_to_text(self):
        # type: () -> str
        return self._text

    @property
    def parent_element(self):
        # type: () -> Optional[Deb822Element]
        return resolve_ref(self._parent_element)

    @parent_element.setter
    def parent_element(self, new_parent):
        # type: (Optional[Deb822Element]) -> None
        self._parent_element = weakref.ref(new_parent) if new_parent is not None else None

    def clear_parent_if_parent(self, parent):
        # type: (Deb822Element) -> None
        if parent is self.parent_element:
            self._parent_element = None


class Deb822WhitespaceToken(Deb822Token):
    """The token is a kind of whitespace.

    Some whitespace tokens are critical for the format (such as the Deb822ValueContinuationToken,
    spaces that separate words in list separated by spaces or newlines), while other whitespace
    tokens are truly insignificant (space before a newline, space after a comma in a comma
    list, etc.).
    """

    __slots__ = ()

    @property
    def is_whitespace(self):
        # type: () -> bool
        return True


class Deb822SemanticallySignificantWhiteSpace(Deb822WhitespaceToken):
    """Whitespace that (if removed) would change the meaning of the file (or cause syntax errors)"""

    __slots__ = ()


class Deb822NewlineAfterValueToken(Deb822SemanticallySignificantWhiteSpace):
    """The newline after a value token.

    If not followed by a continuation token, this also marks the end of the field.
    """

    __slots__ = ()

    def __init__(self):
        # type: () -> None
        super().__init__('\n')


class Deb822ValueContinuationToken(Deb822SemanticallySignificantWhiteSpace):
    """The whitespace denoting a value spanning an additional line (the first space on a line)"""

    __slots__ = ()

    def __init__(self):
        # type: () -> None
        super().__init__(' ')


class Deb822SpaceSeparatorToken(Deb822SemanticallySignificantWhiteSpace):
    """Whitespace between values in a space list (e.g. "Architectures")"""

    __slots__ = ()


class Deb822ErrorToken(Deb822Token):
    """Token that represents a syntactical error"""

    __slots__ = ()


class Deb822CommentToken(Deb822Token):

    __slots__ = ()

    @property
    def is_comment(self):
        # type: () -> bool
        return True


class Deb822FieldNameToken(Deb822Token):

    __slots__ = ()

    def __init__(self, text):
        # type: (str) -> None
        if not isinstance(text, _strI):
            text = _strI(sys.intern(text))
        super().__init__(text)

    @property
    def text(self):
        # type: () -> _strI
        return cast('_strI', self._text)


# The colon after the field name, parenthesis, etc.
class Deb822SeparatorToken(Deb822Token):

    __slots__ = ()


class Deb822FieldSeparatorToken(Deb822Token):

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(':')


class Deb822CommaToken(Deb822SeparatorToken):
    """Used by the comma-separated list value parsers to denote a comma between two value tokens."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(',')


class Deb822PipeToken(Deb822SeparatorToken):
    """Used in some dependency fields as OR relation"""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__('|')


class Deb822ValueToken(Deb822Token):
    """A field value can be split into multi "Deb822ValueToken"s (as well as separator tokens)"""

    __slots__ = ()


# TODO: This should probably be converted into an Element of some form
class Deb822ParsedMultilineValueToken(Deb822ValueToken):
    """Special token used in interpreted values where the value can contain newlines"""

    __slots__ = ()

    def _verify_token_text(self):
        # type: () -> None
        if self._text[0].isspace() or self._text[-1].isspace():
            raise ValueError(self.__class__.__name__ +
                             " tokens MUST NOT start nor end on whitespace")


class Deb822ValueDependencyToken(Deb822Token):
    """Package name, architecture name, a version number, or a profile name in a dependency field"""

    __slots__ = ()


class Deb822ValueDependencyVersionRelationOperatorToken(Deb822Token):

    __slots__ = ()


def tokenize_deb822_file(sequence: Iterable[Union[str, bytes]]) -> Iterable[Deb822Token]:
    # type(Iterable[Union[str, bytes]]) -> Iterable[Deb822Token]
    """Tokenize a deb822 file

    :param sequence: An iterable of lines (a file open for reading will do)
    """
    current_field_name = None
    field_name_cache = {}  # type: Dict[str, _strI]

    def _as_str(s: Iterable[Union[str, bytes]]) -> Iterable[str]:
        for x in s:
            if isinstance(x, bytes):
                x = x.decode('utf-8')
            yield x

    text_stream = BufferingIterator(_as_str(sequence))  # type: BufferingIterator[str]

    for no, line in enumerate(text_stream, start=1):

        if not line.endswith("\n"):
            # We expect newlines at the end of each line except the last.
            if text_stream.peek() is not None:
                raise ValueError("Invalid line iterator: Line " + str(no) + " did not end on a"
                                 " newline and it is not the last line in the stream!")
            if line == '':
                raise ValueError("Line " + str(no) + " was completely empty.  The tokenizer expects"
                                 " whitespace (including newlines) to be present")
        if _RE_WHITESPACE_LINE.match(line):
            if current_field_name:
                # Blank lines terminate fields
                current_field_name = None

            # If there are multiple whitespace-only lines, we combine them
            # into one token.
            r = list(text_stream.takewhile(lambda x: _RE_WHITESPACE_LINE.match(x) is not None))
            if r:
                line += "".join(r)

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
