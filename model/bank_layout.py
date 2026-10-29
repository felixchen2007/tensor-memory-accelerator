"""Word-addressed four-bank layout, with an explicit reversible mapping."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BankLayout:
    row_width: int = 10
    swizzle: bool = False
    shift: int = 5

    def __post_init__(self):
        if self.row_width < 1:
            raise ValueError("row_width must be positive")
        if self.swizzle and not 2 <= self.shift <= self.row_width:
            raise ValueError("Enabled swizzle requires 2 <= shift <= row_width")

    @property
    def words(self) -> int:
        return 4 * (1 << self.row_width)

    def decode(self, word: int) -> tuple[int, int]:
        if not 0 <= word < self.words:
            raise ValueError("Logical word outside scratchpad")
        low = word % 4
        row = word // 4
        bank = low ^ ((word // (1 << self.shift)) % 4) if self.swizzle else low
        return bank, row

    def encode(self, bank: int, row: int) -> int:
        if not 0 <= bank < 4 or not 0 <= row < (1 << self.row_width):
            raise ValueError("Physical bank/row outside scratchpad")
        high = row * 4
        low = bank ^ ((high // (1 << self.shift)) % 4) if self.swizzle else bank
        return high + low

    def service_cycles(self, words: list[int]) -> int:
        """Minimum issue cycles for an all-ready batch, one request per lane."""
        if len(words) != 4:
            raise ValueError("A comparison batch must contain exactly four requests")
        counts = [0] * 4
        for word in words:
            bank, _ = self.decode(word)
            counts[bank] += 1
        return max(counts)
