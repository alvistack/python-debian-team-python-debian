import dataclasses
import itertools
import sys

from typing import Optional, TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from typing import Self
    from debian._deb822_repro.parsing import Deb822Element


_DATA_CLASS_OPTIONAL_ARGS = {}
if sys.version_info >= (3, 10):
    # The `slots` feature greatly reduces the memory usage by avoiding the `__dict__`
    # instance. But at the end of the day, performance is "nice to have" for this
    # feature and all current consumers are at Python 3.12 (except the CI tests...)
    _DATA_CLASS_OPTIONAL_ARGS["slots"] = True


@dataclasses.dataclass(frozen=True, **_DATA_CLASS_OPTIONAL_ARGS)
class TEPosition:
    """Describes a "cursor" position inside a file

    It consists of a line position (0-based line number) and a cursor position.  This is modelled
    after the "Position" in Language Server Protocol (LSP).
    """
    line_position: int
    """Describes the line position as a 0-based line number

    See line_number if you want a human readable line number
    """
    cursor_position: int
    """Describes a cursor position ("between two characters") or a character offset.

    When this value is 0, the position is at the start of a line. When it is 1, then
    the position is between the first and the second character (etc.).
    """

    @property
    def line_number(self) -> int:
        """The line number as human would count it"""
        return self.line_position + 1

    def relative_to(self, new_base: "TEPosition") -> "TEPosition":
        if self.line_position == 0 and self.cursor_position == 0:
            return new_base
        if new_base.line_position == 0 and new_base.cursor_position == 0:
            return self
        if self.line_position == 0:
            line_number = new_base.line_position
            line_char_offset = new_base.cursor_position + self.cursor_position
        else:
            line_number = self.line_position + new_base.line_position
            line_char_offset = self.cursor_position
        return TEPosition(
            line_number,
            line_char_offset,
        )


@dataclasses.dataclass(frozen=True, **_DATA_CLASS_OPTIONAL_ARGS)
class TERange:
    """Describes a range inside a file

    This can be useful to describe things like "from line 4, cursor position 2
    to line 7 to cursor position 10". When describing a full line including the
    newline, use line N, cursor position 0 to line N+1. cursor position 0.

    It is also used to denote the size of objects (in that case, the start position
    is set to START_POSITION as a convention if the precise location is not
    specified).

    This is modelled after the "Range" in Language Server Protocol (LSP).
    """
    start_pos: TEPosition
    end_pos: TEPosition

    @property
    def start_line_position(self) -> int:
        return self.start_pos.line_position

    @property
    def start_cursor_position(self) -> int:
        return self.start_pos.cursor_position

    @property
    def start_line_number(self) -> int:
        return self.start_pos.line_number

    @property
    def end_line_position(self) -> int:
        return self.end_pos.line_position

    @property
    def end_line_number(self) -> int:
        return self.end_pos.line_number

    @property
    def end_cursor_position(self) -> int:
        return self.end_pos.cursor_position

    @property
    def line_count(self) -> int:
        return self.end_line_position - self.start_line_position

    @classmethod
    def between(cls, a: TEPosition, b: TEPosition) -> "Self":
        if a.line_position > b.line_position or \
           (a.line_position == b.line_position and a.cursor_position > b.cursor_position):
            # Order swap, so `a` is always the earliest position
            a, b = b, a
        return cls(
            a,
            b,
        )

    def rebase(self, new_start_position: TEPosition) -> "TERange":
        if new_start_position == self.start_pos:
            return self
        line_count = self.line_count
        new_end_line = new_start_position.line_position + line_count
        if line_count:
            new_end_cursor_position = self.end_cursor_position
        else:
            delta = self.end_cursor_position - self.start_cursor_position
            new_end_cursor_position = new_start_position.cursor_position + delta
        return TERange(
            new_start_position,
            TEPosition(
                new_end_line,
                new_end_cursor_position,
            )
        )

    @classmethod
    def from_position_and_size(cls, base: TEPosition, size: "TERange") -> "Self":
        line_position = base.line_position
        cursor_position = base.cursor_position
        # ranges are not guaranteed to be sizes, but by rebasing them to the start position
        # we ensure they will be. Note rebase optimizes for this use-case, so it is cheap
        # to just blindly throw rebase at this problem.
        size_rebased = size.rebase(START_POSITION)
        lines = size_rebased.line_count
        if lines:
            line_position += lines
            cursor_position = size_rebased.end_cursor_position
        else:
            delta = size_rebased.end_cursor_position - size_rebased.start_cursor_position
            cursor_position += delta
        return cls(
            base,
            TEPosition(
                line_position,
                cursor_position,
            )
        )

    @classmethod
    def from_position_and_sizes(cls, base: TEPosition, sizes: Iterable["TERange"]) -> "Self":
        line_position = base.line_position
        cursor_position = base.cursor_position
        for size in sizes:
            # ranges are not guaranteed to be sizes, but by rebasing them to the start position
            # we ensure they will be. Note rebase optimizes for this use-case, so it is cheap
            # to just blindly throw rebase at this problem.
            size_rebased = size.rebase(START_POSITION)
            lines = size_rebased.line_count
            if lines:
                line_position += lines
                cursor_position = size_rebased.end_cursor_position
            else:
                delta = size_rebased.end_cursor_position - size_rebased.start_cursor_position
                cursor_position += delta
        return cls(
            base,
            TEPosition(
                line_position,
                cursor_position,
            )
        )


START_POSITION = TEPosition(0, 0)
SECOND_CHAR_POS = TEPosition(0, 1)
SECOND_LINE_POS = TEPosition(1, 0)
ONE_CHAR_RANGE = TERange.between(START_POSITION, SECOND_CHAR_POS)
ONE_LINE_RANGE = TERange.between(START_POSITION, SECOND_LINE_POS)


class Locatable:
    __slots__ = ()

    @property
    def parent_element(self):
        # type: () -> Optional[Deb822Element]
        raise NotImplementedError

    def position_in_parent(self, *, skip_leading_comments: bool = True) -> TEPosition:
        """The start position of this token/element inside its parent

        This is operation is generally linear to the number of "parts" (elements/tokens)
        inside the parent.

        :param skip_leading_comments: If True, then if any leading comment that
          that can be skipped will be excluded in the position of this locatable.
          This is useful if you want the position "semantic" content of a field
          without also highlighting a leading comment. Remember to align this
          parameter with the `te_size` call, so the range does not "overshoot"
          into the next element (or falls short and only covers part of an
          element). Note that this option can only be used to filter out leading
          comments when the comments are a subset of the element. It has no
          effect on elements that are entirely made of comments.
        """
        # pylint: disable=unused-argument
        # Note: The base class makes no assumptions about what tokens can be skipped,
        # therefore, skip_leading_comments is unused here. However, I do not want the
        # API to differ between elements and tokens.

        parent = self.parent_element
        if parent is None:
            raise TypeError("Cannot determine the position since the object is detached")
        relevant_parts = itertools.takewhile(lambda x: x is not self, parent.iter_parts())
        span = TERange.from_position_and_sizes(
            START_POSITION,
            (x.te_size(skip_leading_comments=False) for x in relevant_parts),
        )
        return span.end_pos

    def position_in_file(self, *, skip_leading_comments: bool = True) -> TEPosition:
        """The start position of this token/element in this file

        This is an *expensive* operation and in many cases have to traverse
        the entire file structure to answer the query.  Consider whether
        you can maintain the parent's position and then use
        `position_in_parent()` combined with
        `child_position.relative_to(parent_position)`

        :param skip_leading_comments: If True, then if any leading comment that
          that can be skipped will be excluded in the position of this locatable.
          This is useful if you want the position "semantic" content of a field
          without also highlighting a leading comment. Remember to align this
          parameter with the `te_size` call, so the range does not "overshoot"
          into the next element (or falls short and only covers part of an
          element). Note that this option can only be used to filter out leading
          comments when the comments are a subset of the element. It has no
          effect on elements that are entirely made of comments.
        """
        position = self.position_in_parent(
            skip_leading_comments=skip_leading_comments,
        )
        parent = self.parent_element
        if parent is not None:
            parent_position = parent.position_in_file(skip_leading_comments=False)
            position = position.relative_to(parent_position)
        return position

    def te_size(self, *, skip_leading_comments: bool = True) -> TERange:
        """Describe the objects size as a continuous range

        :param skip_leading_comments: If True, then if any leading comment that
          that can be skipped will be excluded in the position of this locatable.
          This is useful if you want the position "semantic" content of a field
          without also highlighting a leading comment. Remember to align this
          parameter with the `position_in_file` or `position_in_parent` call,
          so the range does not "overshoot" into the next element (or falls
          short and only covers part of an element).  Note that this option can
          only be used to filter out leading comments when the comments are a
          subset of the element. It has no effect on elements that are entirely
          made of comments.
        """
        raise NotImplementedError
