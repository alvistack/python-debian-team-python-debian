import sys
from weakref import ReferenceType
from typing import Optional, cast, TYPE_CHECKING
import weakref

from debian._deb822_repro._util import resolve_ref
from debian.deb822 import _strI


if TYPE_CHECKING:
    from debian._deb822_repro.parsing import Deb822Element


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

    # To support callers that want a simple interface for converting tokens and elements to text
    def convert_to_text(self) -> str:
        return self._text

    @property
    def parent_element(self) -> 'Optional[Deb822Element]':
        return resolve_ref(self._parent_element)

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

    __slots__ = ()

    @property
    def is_whitespace(self) -> bool:
        return True


class Deb822SemanticallySignificantWhiteSpace(Deb822WhitespaceToken):
    """Whitespace that (if removed) would change the meaning of the file (or cause syntax errors)"""

    __slots__ = ()


class Deb822NewlineAfterValueToken(Deb822SemanticallySignificantWhiteSpace):
    """The newline after a value token.

    If not followed by a continuation token, this also marks the end of the field.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__('\n')


class Deb822ValueContinuationToken(Deb822SemanticallySignificantWhiteSpace):
    """The whitespace denoting a value spanning an additional line (the first space on a line)"""

    __slots__ = ()

    def __init__(self) -> None:
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
    def is_comment(self) -> bool:
        return True


class Deb822FieldNameToken(Deb822Token):

    __slots__ = ()

    def __init__(self, text: str) -> None:
        if not isinstance(text, _strI):
            text = _strI(sys.intern(text))
        super().__init__(text)

    @property
    def text(self) -> _strI:
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


class Deb822ValueDependencyToken(Deb822Token):
    """Package name, architecture name, a version number, or a profile name in a dependency field"""

    __slots__ = ()


class Deb822ValueDependencyVersionRelationOperatorToken(Deb822Token):

    __slots__ = ()
