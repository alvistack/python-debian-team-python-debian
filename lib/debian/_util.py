import weakref
from weakref import ReferenceType

try:
    from typing import (
        Iterable, Optional, Generic, Dict, List, Iterator, TypeVar, TYPE_CHECKING, Any,
    )

    # Used a generic type for any case where we need a generic type without any bounds
    # (e.g. for the LinkedList interface and some super-classes/mixins).
    T = TypeVar('T')
    T.__doc__ = """
    Generic type
    """
except ImportError:  # pragma: no cover
    TYPE_CHECKING = False


def resolve_ref(ref):
    # type: (Optional[ReferenceType[T]]) -> Optional[T]
    return ref() if ref is not None else None


class _CaseInsensitiveString(str):
    """Case insensitive string.
    """
    __slots__ = ['str_lower']

    if TYPE_CHECKING:  # pragma: no cover
        # neither pylint nor mypy cope with str_lower being defined in __new__
        def __init__(self, s):
            # type: (str) -> None
            super(_CaseInsensitiveString, self).__init__(s)   # type: ignore
            self.str_lower = ''

    def __new__(cls, str_):  # type: ignore
        s = str.__new__(cls, str_)
        s.str_lower = str_.lower()
        return s

    def __hash__(self):
        # type: () -> int
        return hash(self.str_lower)

    def __eq__(self, other):
        # type: (Any) -> Any
        try:
            return self.str_lower == other.lower()
        except AttributeError:
            return False

    def lower(self):
        # type: () -> str
        return self.str_lower


_strI = _CaseInsensitiveString


class LinkedListNode(Generic[T]):

    __slots__ = ('_previous_node', 'value', 'next_node', '__weakref__')

    def __init__(self, value):
        # type: (T) -> None
        self._previous_node = None  # type: Optional[ReferenceType[LinkedListNode[T]]]
        self.next_node = None  # type: Optional[LinkedListNode[T]]
        self.value = value

    @property
    def previous_node(self):
        # type: () -> Optional[LinkedListNode[T]]
        return resolve_ref(self._previous_node)

    @previous_node.setter
    def previous_node(self, node):
        # type: (LinkedListNode[T]) -> None
        self._previous_node = weakref.ref(node) if node is not None else None

    def remove(self):
        # type: () -> T
        LinkedListNode.link_nodes(self.previous_node, self.next_node)
        self.previous_node = None
        self.next_node = None
        return self.value

    def iter_next(self, *,
                  skip_current=False  # type: Optional[bool]
                  ):
        # type: (...) -> Iterator[LinkedListNode[T]]
        node = self.next_node if skip_current else self
        while node:
            yield node
            node = node.next_node

    def iter_previous(self, *,
                      skip_current=False  # type: Optional[bool]
                      ):
        # type: (...) -> Iterator[LinkedListNode[T]]
        node = self.previous_node if skip_current else self
        while node:
            yield node
            node = node.previous_node

    @staticmethod
    def link_nodes(previous_node, next_node):
        # type: (Optional[LinkedListNode[T]], Optional['LinkedListNode[T]']) -> None
        if next_node:
            next_node.previous_node = previous_node
        if previous_node:
            previous_node.next_node = next_node

    @staticmethod
    def _insert_link(first_node,  # type: Optional[LinkedListNode[T]]
                     new_node,  # type: LinkedListNode[T]
                     last_node,  # type: Optional[LinkedListNode[T]]
                     ):
        # type: (...) -> None
        LinkedListNode.link_nodes(first_node, new_node)
        LinkedListNode.link_nodes(new_node, last_node)

    def insert_before(self, new_node):
        # type: (LinkedListNode[T]) -> None
        assert self is not new_node and new_node is not self.previous_node
        LinkedListNode._insert_link(self.previous_node, new_node, self)

    def insert_after(self, new_node):
        # type: (LinkedListNode[T]) -> None
        assert self is not new_node and new_node is not self.next_node
        LinkedListNode._insert_link(self, new_node, self.next_node)


class LinkedList(Generic[T]):
    """Specialized linked list implementation to support the deb822 parser needs

    We deliberately trade "encapsulation" for features needed by this library
    to facilitate their implementation.  Notably, we allow nodes to leak and assume
    well-behaved calls to remove_node - because that makes it easier to implement
    components like Deb822InvalidParagraphElement.
    """

    __slots__ = ('head_node', 'tail_node', '_size')

    def __init__(self, values=None):
        # type: (Optional[Iterable[T]]) -> None
        self.head_node = None  # type: Optional[LinkedListNode[T]]
        self.tail_node = None  # type: Optional[LinkedListNode[T]]
        self._size = 0
        if values is not None:
            self.extend(values)

    def __bool__(self):
        # type: () -> bool
        return self.head_node is not None

    def __len__(self):
        # type: () -> int
        return self._size

    @property
    def tail(self):
        # type: () -> Optional[T]
        return self.tail_node.value if self.tail_node is not None else None

    def pop(self):
        # type: () -> None
        if self.tail_node is None:
            raise IndexError('pop from empty list')
        self.remove_node(self.tail_node)

    def iter_nodes(self):
        # type: () -> Iterator[LinkedListNode[T]]
        head_node = self.head_node
        if head_node is None:
            return
        yield from head_node.iter_next()

    def __iter__(self):
        # type: () -> Iterator[T]
        yield from (node.value for node in self.iter_nodes())

    def __reversed__(self):
        # type: () -> Iterator[T]
        tail_node = self.tail_node
        if tail_node is None:
            return
        yield from (n.value for n in tail_node.iter_previous())

    def remove_node(self, node):
        # type: (LinkedListNode[T]) -> None
        if node is self.head_node:
            self.head_node = node.next_node
            if self.head_node is None:
                self.tail_node = None
        elif node is self.tail_node:
            self.tail_node = node.previous_node
            # That case should have happened in the "if node is self._head"
            # part
            assert self.tail_node is not None
        assert self._size > 0
        self._size -= 1
        node.remove()

    def append(self, value):
        # type: (T) -> LinkedListNode[T]
        node = LinkedListNode(value)
        if self.head_node is None:
            self.head_node = node
            self.tail_node = node
        else:
            # Primarily as a hint to mypy
            assert self.tail_node is not None
            self.tail_node.insert_after(node)
            self.tail_node = node
        self._size += 1
        return node

    def insert_before(self, value, existing_node):
        # type: (T, LinkedListNode[T]) -> LinkedListNode[T]
        new_node = LinkedListNode(value)
        if self.head_node is None:
            raise ValueError("List is empty; node argument cannot be valid")
        existing_node.insert_before(new_node)
        if existing_node is self.head_node:
            self.head_node = new_node
        self._size += 1
        return new_node

    def extend(self, values):
        # type: (Iterable[T]) -> None
        for v in values:
            self.append(v)

    def clear(self):
        # type: () -> None
        self.head_node = None
        self.tail_node = None
        self._size = 0


class OrderedSet(object):
    """A set-like object that preserves order when iterating over it

    We use this to keep track of keys in Deb822Dict, because it's much faster
    to look up if a key is in a set than in a list.
    """

    def __init__(self, iterable=None):
        # type: (Optional[Iterable[str]]) -> None

        # We implement the OrderedSet as a "Home-built" LinkedHashSet because
        # python does not provide better facilities for it.  On the flip side,
        # we can add specialized functionality on top of it like "insert after"
        # or "move to the end".
        self.__table = {}  # type: Dict[str, LinkedListNode[str]]
        self.__order = LinkedList()   # type: LinkedList[str]
        if iterable is None:
            iterable = []
        for item in iterable:
            self.add(item)

    def add(self, item):
        # type: (str) -> None
        if item not in self:
            # We rely on the dict to raise an exception if the item is unhashable
            # Unfortunately, we need to add it to the linked list first (to obtain
            # the node) which makes this a bit more cumbersome than one might have
            # hoped.
            node = self.__order.append(item)
            try:
                self.__table[item] = node
            except Exception:
                self.__order.remove_node(node)
                raise

    def remove(self, item):
        # type: (str) -> None
        # The dict will raise KeyError, so we don't need to handle that
        # ourselves
        node = self.__table[item]
        del self.__table[item]
        self.__order.remove_node(node)

    def __iter__(self):
        # type: () -> Iterator[str]
        # Return an iterator of items in the order they were added
        return iter(self.__order)

    def __reversed__(self):
        # type: () -> Iterator[str]
        # Return an iterator of items in the opposite order they were added
        return iter(reversed(self.__order))

    def __len__(self):
        # type: () -> int
        return len(self.__order)

    def __contains__(self, item):
        # type: (str) -> bool
        # This is what makes OrderedSet faster than using a list to keep track
        # of keys.  Lookup in a dict is O(1) instead of O(n) for a list.
        return item in self.__table

    # ### list-like methods
    append = add

    def extend(self, iterable):
        # type: (Iterable[str]) -> None
        for item in iterable:
            self.add(item)
