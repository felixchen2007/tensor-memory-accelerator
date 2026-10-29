"""16-bit copy oracle with separate source/destination word arrays."""

from dataclasses import dataclass
from enum import IntEnum

from model.address_model import Descriptor, addresses


class ErrorCode(IntEnum):
    OK = 0
    EMPTY = 1
    ALIGNMENT = 2
    BOUNDS = 3
    READ = 4
    WRITE = 5


@dataclass
class CopyResult:
    destination: list[int]
    error_code: ErrorCode
    completed_elements: int
    reads: list[int]
    writes: list[tuple[int, int]]


def copy_tensor(desc: Descriptor, source: list[int], destination: list[int],
                read_fault: int | None = None,
                write_fault: int | None = None) -> CopyResult:
    """Model serialized execution, including partial completion on error.

    Fault indices are zero-based element/transaction indices. This oracle's
    write-fault endpoint leaves the failed word unchanged; actual adapters may
    leave the affected word unspecified after a failed write response.
    """
    desc.validate()
    if not source or not destination:
        raise ValueError("Memory endpoints must contain at least one 16-bit word")
    for memory in (source, destination):
        if any(not isinstance(v, int) or not 0 <= v <= 0xFFFF for v in memory):
            raise ValueError("Memory values must fit 16 bits")
    if any(i is not None and i < 0 for i in (read_fault, write_fault)):
        raise ValueError("Fault indices must be nonnegative")
    result = CopyResult(list(destination), ErrorCode.OK, 0, [], [])
    if desc.is_empty:
        result.error_code = ErrorCode.EMPTY
        return result
    src_fields = (desc.src_base, desc.src_row_stride, desc.src_col_stride)
    dst_fields = (desc.dst_base, desc.dst_row_stride, desc.dst_col_stride)
    if any(value & 1 for value in src_fields + dst_fields):
        result.error_code = ErrorCode.ALIGNMENT
        return result
    if (any(value > 2 * len(source) - 2 for value in src_fields) or
            any(value > 2 * len(destination) - 2 for value in dst_fields)):
        result.error_code = ErrorCode.BOUNDS
        return result
    for index, (src, dst, _) in enumerate(addresses(desc)):
        if src >= 2 * len(source) or dst >= 2 * len(destination):
            result.error_code = ErrorCode.BOUNDS
            break
        result.reads.append(src)
        if index == read_fault:
            result.error_code = ErrorCode.READ
            break
        value = source[src // 2]
        result.writes.append((dst, value))
        if index == write_fault:
            result.error_code = ErrorCode.WRITE
            break
        result.destination[dst // 2] = value
        result.completed_elements += 1
    return result
