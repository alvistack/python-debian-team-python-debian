import logging
import weakref
from typing import Optional, Union, Iterable, Callable, TYPE_CHECKING, Generic, Iterator
from weakref import ReferenceType

from debian._deb822_repro.types import T, TokenOrElement


if TYPE_CHECKING:
    from debian._deb822_repro.parsing import Deb822Element


def resolve_ref(ref: Optional[ReferenceType[T]]) -> Optional[T]:
    return ref() if ref is not None else None


def print_ast(ast_tree: Union[Iterable[TokenOrElement], 'Deb822Element'], *,
              end_marker_after: Optional[int] = 5,
              output_function: Optional[Callable[[str], None]] = None,
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
    :param output_function: Callable that receives a single str argument and is responsible
      for "displaying" that line. The callable may be invoked multiple times (one per line
      of output).  Defaults to logging.info if omitted.

    """
    # Avoid circular dependency
    # pylint: disable=import-outside-toplevel
    from debian._deb822_repro.parsing import Deb822Element
    prefix = None
    if isinstance(ast_tree, Deb822Element):
        ast_tree = [ast_tree]
    stack = [(0, '', iter(ast_tree))]
    current_no = 0
    if output_function is None:
        output_function = logging.info
    while stack:
        start_no, name, current_iter = stack[-1]
        for current in current_iter:
            current_no += 1
            if prefix is None:
                prefix = '  ' * len(stack)
            if isinstance(current, Deb822Element):
                stack.append((current_no, current.__class__.__name__, iter(current.iter_parts())))
                output_function(f"{prefix}{current.__class__.__name__}")
                prefix = None
                break
            output_function(f"{prefix}{current}")
        else:
            # current_iter is depleted
            stack.pop()
            prefix = None
            if end_marker_after is not None and start_no + end_marker_after <= current_no and name:
                if prefix is None:
                    prefix = '  ' * len(stack)
                output_function(f"{prefix}# <-- END OF {name}")


class LinkedListNode(Generic[T]):

    __slots__ = ('_previous_node', 'value', 'next_node', '__weakref__')

    def __init__(self, value: T):
        self._previous_node: 'Optional[ReferenceType[LinkedListNode[T]]]' = None
        self.next_node: 'Optional[LinkedListNode[T]]' = None
        self.value = value

    @property
    def previous_node(self) -> 'Optional[LinkedListNode[T]]':
        return resolve_ref(self._previous_node)

    @previous_node.setter
    def previous_node(self, node: 'LinkedListNode[T]') -> None:
        self._previous_node = weakref.ref(node) if node is not None else None

    def remove(self) -> T:
        LinkedListNode.link_nodes(self.previous_node, self.next_node)
        self.previous_node = None
        self.next_node = None
        return self.value

    def iter_next(self, *, skip_current: bool = False) -> Iterator['LinkedListNode[T]']:
        node = self.next_node if skip_current else self
        while node:
            yield node
            node = node.next_node

    def iter_previous(self, *, skip_current: bool = False) -> Iterator['LinkedListNode[T]']:
        node = self.previous_node if skip_current else self
        while node:
            yield node
            node = node.previous_node

    @staticmethod
    def link_nodes(previous_node: Optional['LinkedListNode[T]'],
                   next_node: Optional['LinkedListNode[T]']) -> None:
        if next_node:
            next_node.previous_node = previous_node
        if previous_node:
            previous_node.next_node = next_node

    @staticmethod
    def _insert_link(first_node: Optional['LinkedListNode[T]'],
                     new_node: 'LinkedListNode[T]',
                     last_node: Optional['LinkedListNode[T]']
                     ) -> None:
        LinkedListNode.link_nodes(first_node, new_node)
        LinkedListNode.link_nodes(new_node, last_node)

    def insert_after(self, new_node: 'LinkedListNode[T]') -> None:
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

    def __init__(self, values: Optional[Iterable[T]] = None, /) -> None:
        self.head_node: Optional[LinkedListNode[T]] = None
        self.tail_node: Optional[LinkedListNode[T]] = None
        self._size = 0
        if values is not None:
            self.extend(values)

    def __bool__(self) -> bool:
        return self.head_node is not None

    def __len__(self) -> int:
        return self._size

    @property
    def tail(self) -> Optional[T]:
        return self.tail_node.value if self.tail_node is not None else None

    def pop(self) -> None:
        if self.tail_node is None:
            raise IndexError('pop from empty list')
        self.remove_node(self.tail_node)

    def iter_nodes(self) -> Iterator[LinkedListNode[T]]:
        head_node = self.head_node
        if head_node is None:
            return
        yield from head_node.iter_next()

    def __iter__(self) -> Iterator[T]:
        yield from (node.value for node in self.iter_nodes())

    def __reversed__(self) -> Iterator[T]:
        tail_node = self.tail_node
        if tail_node is None:
            return
        yield from (n.value for n in tail_node.iter_previous())

    def remove_node(self, node: LinkedListNode[T]) -> None:
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

    def append(self, value: T) -> LinkedListNode[T]:
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

    def extend(self, values: Iterable[T]) -> None:
        for v in values:
            self.append(v)

    def clear(self) -> None:
        self.head_node = None
        self.tail_node = None
        self._size = 0
