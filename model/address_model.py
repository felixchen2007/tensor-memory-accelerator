"""Mathematical address oracle; intentionally independent of RTL state updates."""

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Descriptor:
    src_base: int
    dst_base: int
    rows: int
    cols: int
    src_row_stride: int
    src_col_stride: int
    dst_row_stride: int
    dst_col_stride: int

    def validate(self, addr_width: int = 32, count_width: int = 16) -> None:
        if addr_width < 1 or count_width < 1:
            raise ValueError("Address and count widths must be positive")
        for name in ("src_base", "dst_base", "src_row_stride", "src_col_stride",
                     "dst_row_stride", "dst_col_stride"):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value < (1 << addr_width):
                raise ValueError(f"{name} must fit an unsigned {addr_width}-bit field")
        for name in ("rows", "cols"):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value < (1 << count_width):
                raise ValueError(f"{name} must fit an unsigned {count_width}-bit field")

    @property
    def element_count(self) -> int:
        return self.rows * self.cols

    @property
    def is_empty(self) -> bool:
        return self.rows == 0 or self.cols == 0


def addresses(descriptor: Descriptor, addr_width: int = 32,
              count_width: int = 16) -> Iterator[tuple[int, int, bool]]:
    """Yield (source byte address, destination byte address, last) per element.

    Empty descriptors yield nothing. The RTL additionally pulses done/error for
    them. Physical address bounds/alignment are not this primitive's contract.
    """
    descriptor.validate(addr_width, count_width)
    mask = (1 << addr_width) - 1
    for row in range(descriptor.rows):
        for col in range(descriptor.cols):
            src = (descriptor.src_base + row * descriptor.src_row_stride +
                   col * descriptor.src_col_stride) & mask
            dst = (descriptor.dst_base + row * descriptor.dst_row_stride +
                   col * descriptor.dst_col_stride) & mask
            last = row == descriptor.rows - 1 and col == descriptor.cols - 1
            yield src, dst, last
