import collections
import collections.abc
import logging
import textwrap
import weakref
from weakref import ReferenceType

try:
    from typing import (
        Optional, Union, Iterable, Callable, TYPE_CHECKING, Generic, Iterator,
        Type, cast, List,
    )
    from debian._deb822_repro.types import T, TE, R, TokenOrElement

    _combine_parts_ret_type = Callable[
        [Iterable[Union[TokenOrElement, TE]]],
        Iterable[Union[TokenOrElement, R]]
    ]
except ImportError:
    TYPE_CHECKING = False
    cast = lambda t, v: v


if TYPE_CHECKING:
    from debian._deb822_repro.parsing import Deb822Element
    from debian._deb822_repro.tokens import Deb822Token


def resolve_ref(ref):
    # type: (Optional[ReferenceType[T]]) -> Optional[T]
    return ref() if ref is not None else None


def print_ast(ast_tree,  # type: Union[Iterable[TokenOrElement], 'Deb822Element']
              *,
              end_marker_after=5,  # type: Optional[int]
              output_function=None,  # type: Optional[Callable[[str], None]]
              ):
    # type: (...) -> None
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
                output_function(prefix + current.__class__.__name__)
                prefix = None
                break
            output_function(prefix + str(current))
        else:
            # current_iter is depleted
            stack.pop()
            prefix = None
            if end_marker_after is not None and start_no + end_marker_after <= current_no and name:
                if prefix is None:
                    prefix = '  ' * len(stack)
                output_function(prefix + "# <-- END OF " + name)


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


def combine_into_replacement(source_class,  # type: Type[TE]
                             replacement_class,  # type: Type[R]
                             *,
                             constructor=None,  # type: Optional[Callable[[List[TE]], R]]
                             ):
    # type: (...) -> _combine_parts_ret_type[TE, R]
    """Combines runs of one type into another type

    This is primarily useful for transforming tokens (e.g, Comment tokens) into
    the relevant element (such as the Comment element).
    """
    if constructor is None:
        _constructor = cast('Callable[[List[TE]], R]', replacement_class)
    else:
        # Force mypy to see that constructor is no longer optional
        _constructor = constructor

    def _impl(token_stream):
        # type: (Iterable[Union[TokenOrElement, TE]]) -> Iterable[Union[TokenOrElement, R]]
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


class BufferingIterator(collections.abc.Iterator[T]):

    def __init__(self, stream: Iterable[T]) -> None:
        self._stream = iter(stream)  # type: Iterator[T]
        self._buffer = collections.deque()  # type: collections.deque[T]
        self._expired = False  # type: bool

    def __next__(self):
        # type: () -> T
        if self._buffer:
            return self._buffer.popleft()
        if self._expired:
            raise StopIteration
        return next(self._stream)

    def takewhile(self, predicate):
        # type: (Callable[[T], bool]) -> Iterable[T]
        """Variant of itertools.takewhile except it does not discard the first non-matching token"""
        buffer = self._buffer
        while buffer or self._fill_buffer(5):
            v = buffer[0]
            if predicate(v):
                buffer.popleft()
                yield v
            else:
                break

    def _fill_buffer(self, number):
        # type: (int) -> bool
        if not self._expired:
            while len(self._buffer) < number:
                try:
                    self._buffer.append(next(self._stream))
                except StopIteration:
                    self._expired = True
                    break
        return bool(self._buffer)

    def peek(self):
        # type: () -> Optional[T]
        return self.peek_at(1)

    def peek_at(self, tokens_ahead):
        # type: (int) -> Optional[T]
        self._fill_buffer(tokens_ahead)
        return self._buffer[tokens_ahead - 1] if self._buffer else None

    def peek_many(self, number):
        # type: (int) -> List[T]
        self._fill_buffer(number)
        return list(self._buffer)


def flatten_with_len_check(line,  # type: str
                           stream,  # type: Iterable[TokenOrElement]
                           line_len=None,  # type: Optional[int]
                           ):
    # type: (...) -> Iterable[Deb822Token]
    """Flatten a parser's output into tokens and verify it covers the entire line/text"""
    if line_len is None:
        line_len = len(line)
    # Fail-safe to ensure none of the value parsers incorrectly parse a value.
    covered = 0
    for token_or_element in stream:
        # We use the AttributeError to discriminate between elements and tokens
        # The cast()s are here to assist / workaround mypy not realizing that.
        try:
            tokens = cast('Deb822Element', token_or_element).iter_tokens()
        except AttributeError:
            token = cast('Deb822Token', token_or_element)
            covered += len(token.text)
            yield token
        else:
            for token in tokens:
                covered += len(token.text)
                yield token
    if covered != line_len:
        if covered < line_len:
            msg = textwrap.dedent("""\
            Value parser did not fully cover the entire line with tokens (
            missing range {covered}..{line_len}).  Occurred when parsing "{line}"
            """).format(covered=covered, line_len=line_len, line=line)
            raise ValueError(msg)
        msg = textwrap.dedent("""\
                    Value parser emitted tokens for more text than was present?  Should have
                     emitted {line_len} characters, got {covered}. Occurred when parsing "{line}"
                    """).format(covered=covered, line_len=line_len, line=line)
        raise ValueError(msg)
