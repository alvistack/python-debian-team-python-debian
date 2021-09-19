try:
    from typing import TypeVar, Union, Tuple, List, TYPE_CHECKING

    if TYPE_CHECKING:
        from debian._deb822_repro.tokens import Deb822Token, Deb822FieldNameToken
        from debian._deb822_repro.parsing import (
            Deb822Element, Deb822CommentElement, Deb822ParsedValueElement
        )

    # Used a generic type for any case where we need a generic type without any bounds
    # (e.g. for the LinkedList interface and some super-classes/mixins).
    T = TypeVar('T')
    T.__doc__ = """
    Generic type
    """

    TokenOrElement = Union['Deb822Element', 'Deb822Token']
    TE = TypeVar('TE', bound=TokenOrElement)
    TE.__doc__ = """
    Generic "Token or Element" type
    """

    # Used as a resulting element for "mapping" functions that map TE -> R (see _combine_parts)
    R = TypeVar('R', bound='Deb822Element')
    R.__doc__ = """
    For internal usage in _deb822_repro
    """

    VE = TypeVar('VE', bound='Deb822Element')
    VE.__doc__ = """
    Value type/element in a list interpretation of a field value
    """

    ST = TypeVar('ST', bound='Deb822Token')
    ST.__doc__ = """
    Separator type/token in a list interpretation of a field value
    """

    # Internal type for part of the paragraph key.  Used to facility _unpack_key.
    ParagraphKeyBase = Union['Deb822FieldNameToken', str]
    ParagraphKeyBase.__doc__ = """
    For internal usage in _deb822_repro
    """

    ParagraphKey = Union[ParagraphKeyBase, Tuple[str, int]]
    ParagraphKey.__doc__ = """
    Anything accepted as a key for a paragraph field lookup.  The simple case being
    a str. Alternative variants are mostly interesting for paragraphs with repeated
    fields (to enable unambiguous lookups)
    """

    Commentish = Union[List[str], 'Deb822CommentElement']
    Commentish.__doc__ = """
    Anything accepted as input for a Comment. The simple case is the list
    of string (each element being a line of comment). The alternative format is
    there for enable reuse of an existing element (e.g. to avoid "unpacking"
    only to "re-pack" an existing comment element).
    """
except ImportError:
    pass


class AmbiguousDeb822FieldKeyError(KeyError):
    """Specialized version of KeyError to denote a valid but ambiguous field name

    This exception occurs if:
      * the field is accessed via a str on a configured view that does not automatically
        resolve ambiguous field names (see Deb822ParagraphElement.configured_view), AND
      * a concrete paragraph contents a repeated field (which is not valid in deb822
        but the module supports parsing them)

    Note that the default is to automatically resolve ambiguous fields. Accordingly
    you will only see this exception if you have "opted in" on wanting to know that
    the lookup was ambiguous.

    The ambiguity can be resolved by using a tuple of (<field-name>, <filed-index>)
    instead of <field-name>.
    """
