"""System checks through public maintenance and descriptor ports and passive DMA taps."""

from collections import deque
from dataclasses import replace
import json
import os
from pathlib import Path

import cocotb
from cocotb.triggers import FallingEdge

from model.address_model import Descriptor, addresses
from model.copy_model import ErrorCode

SOURCE_BYTES = 1 << 26
DEST_BYTES = 8192


def predict(desc):
    src = (desc.src_base, desc.src_row_stride, desc.src_col_stride)
    dst = (desc.dst_base, desc.dst_row_stride, desc.dst_col_stride)
    if desc.is_empty:
        return [], ErrorCode.EMPTY
    if any(value & 1 for value in src + dst):
        return [], ErrorCode.ALIGNMENT
    if max(src) >= SOURCE_BYTES or max(dst) >= DEST_BYTES:
        return [], ErrorCode.BOUNDS
    prefix = []
    for sa, da, _ in addresses(desc):
        if sa >= SOURCE_BYTES or da >= DEST_BYTES:
            return prefix, ErrorCode.BOUNDS
        prefix.append((sa, da))
    return prefix, ErrorCode.OK


def shape(family, bank, offset, rows=3, cols=4, source_row=None, destination_word=None):
    row = family if source_row is None else source_row
    word = bank * 32 + family * 8 if destination_word is None else destination_word
    strides = [(cols*2, 2, cols*2, 2), (cols*2, 2, 2, rows*2),
               (cols*2+6, 2, cols*2+10, 2), (2, 2048, cols*2, 2),
               (cols*2, 0, cols*2, 2)]
    return Descriptor((bank << 24) + row*2048 + offset*2, word*2, rows, cols, *strides[family])


class DmaCorruption(AssertionError):
    pass


def unpack(value, widths):
    fields = []
    for width in reversed(widths):
        fields.append(value & ((1 << width) - 1))
        value >>= width
    return tuple(reversed(fields))


class Bench:
    # Order follows sampled_flags from the least significant bit upward.
    CHANNELS = (('desc', (32, 32, 16, 16, 32, 32, 32, 32)), ('maint', (1, 1, 32, 16)),
                ('maint_response', (1, 16)), ('read', (32,)), ('read_response', (1, 16)),
                ('write', (32, 16)), ('write_response', (1,)))

    def __init__(self, dut, seed):
        self.dut = dut
        self.signals = {}
        self.seed = seed
        self.source, self.destination = {}, {}
        self.stalled = {}
        self.reads, self.writes = deque(), deque()
        self.maintenance = None
        self.active = None
        self.descriptors = self.read_checks = self.write_checks = self.memory_checks = 0
        self.bins = {key: set() for key in ('bank_family', 'offset', 'status', 'size', 'stall')}
        self.blocked = self.long_hold = False

    def signal(self, name):
        if name not in self.signals:
            self.signals[name] = getattr(self.dut, name)
        return self.signals[name]

    def get(self, name):
        return int(self.signal(name).value)

    def drive(self, **values):
        for name, value in values.items():
            self.signal(name).value = value

    def random(self, limit):
        self.seed ^= (self.seed << 13) & 0xffffffff
        self.seed ^= self.seed >> 17
        self.seed ^= (self.seed << 5) & 0xffffffff
        return self.seed % limit

    async def tick(self):
        # The SV wrapper snapshots handshakes on the rising edge. Read that
        # snapshot after the edge so same-cycle replacements are unambiguous.
        await FallingEdge(self.dut.clk)
        return self.observe()

    def observe(self):
        events = {}
        flags = self.get('sampled_flags')
        done, busy, init_done = unpack(flags >> 14, (1, 1, 1))
        maint_valid = (flags >> 2) & 1
        maint_ready = (flags >> 3) & 1
        if not init_done:
            assert not ((flags & 2) or maint_ready), 'TMA_EARLY_READY'
            return events
        assert not (busy and maint_ready), 'TMA_BUSY'
        self.blocked |= bool(busy and maint_valid)
        for index, (name, widths) in enumerate(self.CHANNELS):
            valid = flags & (1 << (index*2))
            ready = flags & (2 << (index*2))
            if not valid:
                assert name not in self.stalled, f'TMA_STABILITY {name}: valid dropped'
                continue
            payload = unpack(self.get('sampled_' + name), widths)
            assert self.stalled.get(name, payload) == payload, f'TMA_STABILITY {name}: payload changed'
            if ready:
                self.stalled.pop(name, None)
                events[name] = payload
            else:
                self.stalled[name] = payload

        if 'maint' in events:
            assert self.maintenance is None, 'TMA_MAINT_OVERLAP'
            self.maintenance = events['maint']
        if 'maint_response' in events:
            self.check_maintenance(events['maint_response'])

        if 'desc' in events:
            assert self.active is None, 'TMA_OVERLAP'
            self.active = Descriptor(*events['desc'])
            # Predict the legal prefix and its data from the descriptor and
            # public maintenance traffic, independently of the DMA signals.
            prefix, self.status = predict(self.active)
            self.expected = [(sa, da, self.source[sa]) for sa, da in prefix]
            self.read_issued = self.write_issued = self.committed = 0

        # Responses belong to the previous request when both handshakes share an edge.
        if 'read_response' in events:
            assert self.reads, 'TMA_READ_ORPHAN'
            sa, _, expected = self.reads.popleft()
            error, data = events['read_response']
            assert not error, 'TMA_READ_ERROR'
            if data != expected:
                raise DmaCorruption(f'TMA_READ_DATA at {sa:#x}: {data:#x} != {expected:#x}')
            self.read_checks += 1
        if 'write_response' in events:
            assert self.writes, 'TMA_WRITE_ORPHAN'
            _, da, data = self.writes.popleft()
            assert events['write_response'] == (0,), 'TMA_WRITE_ERROR'
            # Update the expected memory when the accepted write completes.
            self.destination[da] = data
            self.committed += 1
        if 'read' in events:
            assert self.active is not None and self.read_issued < len(self.expected), 'TMA_READ_COUNT'
            beat = self.expected[self.read_issued]
            assert events['read'] == (beat[0],), 'TMA_READ_ADDRESS'
            self.reads.append(beat)
            self.read_issued += 1
        if 'write' in events:
            assert self.active is not None and self.write_issued < len(self.expected), 'TMA_WRITE_COUNT'
            beat = self.expected[self.write_issued]
            assert events['write'] == beat[1:], 'TMA_WRITE_DATA'
            self.writes.append(beat)
            self.write_issued += 1
            self.write_checks += 1
        if done:
            assert self.active is not None, 'TMA_DONE_ORPHAN'
            count = len(self.expected)
            code, error, completed = unpack(self.get('sampled_completion'), (3, 1, 32))
            assert code == self.status and error == bool(self.status), 'TMA_STATUS'
            assert completed == count, 'TMA_COMPLETION_COUNT'
            assert not (self.reads or self.writes), 'TMA_PENDING'
            assert self.read_issued == self.write_issued == self.committed == count, 'TMA_INCOMPLETE'
            self.cover_descriptor()
            self.descriptors += 1
            self.active = None
        return events

    def check_maintenance(self, response):
        assert self.maintenance is not None, 'TMA_ORPHAN_RESPONSE'
        write, dst, address, data = self.maintenance
        self.maintenance = None
        error, actual = response
        bad = bool(address & 1 or address >= (DEST_BYTES if dst else SOURCE_BYTES))
        assert error == bad, 'TMA_MAINT_ERROR'
        if bad:
            return
        memory = self.destination if dst else self.source
        if write:
            memory[address] = data
        else:
            assert actual == memory[address], f'TMA_MEMORY_DATA at {address:#x}'
            self.memory_checks += 1

    def cover_descriptor(self):
        d = self.active
        if d.src_col_stride == 0:
            family = 4
        elif d.src_col_stride > 2:
            family = 3
        elif d.dst_row_stride == 2 and d.dst_col_stride > 2:
            family = 1
        else:
            family = 2 if max(d.src_row_stride, d.dst_row_stride) > d.cols*2 else 0
        self.bins['bank_family'].add(((d.src_base >> 24) & 3, family))
        self.bins['offset'].add((d.src_base >> 1) & 3)
        self.bins['status'].add(int(self.status))
        size = d.element_count
        self.bins['size'].add(0 if size == 0 else 1 if size == 1 else 2 if size <= 64 else 3 if size <= 256 else 4)

    async def until(self, event):
        for _ in range(100000):
            events = await self.tick()
            if event in events:
                return events[event]
        raise AssertionError(f'TMA_TIMEOUT waiting for {event}')

    async def host(self, write, dst, address, data=0, hold=0):
        self.drive(maint_req_valid=1, maint_req_write=write, maint_req_dst=dst,
                   maint_req_addr=address, maint_req_data=data, maint_rsp_ready=int(not hold))
        await self.until('maint')
        self.drive(maint_req_valid=0)
        if hold:
            for _ in range(100000):
                await self.tick()
                if 'maint_response' in self.stalled:
                    break
            else:
                raise AssertionError('TMA_TIMEOUT waiting for held maintenance response')
            refresh_start = self.get('refresh_count')
            for _ in range(hold-1):
                await self.tick()
            if hold >= 800:
                assert self.get('refresh_count') > refresh_start, 'TMA_REFRESH_STALLED'
                self.long_hold = True
            self.drive(maint_rsp_ready=1)
        await self.until('maint_response')
        self.drive(maint_rsp_ready=0)
        self.bins['stall'].add(0 if not hold else 1 if hold <= 2 else 2)

    async def scan(self):
        for word in range(4096):
            await self.host(0, 1, word*2, hold=word % 6)

    async def descriptor(self, desc, full_scan=False, check_memory=True):
        prefix, _ = predict(desc)
        for sa, _ in prefix:
            data = ((sa >> 1)*73 ^ (sa >> 13) ^ self.descriptors*997 ^ 0xa55a) & 0xffff
            await self.host(1, 0, sa, data, self.random(6))
        completed = self.descriptors + 1
        self.drive(desc_valid=1, **{'desc_' + k: v for k, v in vars(desc).items()})
        await self.until('desc')
        self.drive(desc_valid=0)
        if prefix and check_memory:
            await self.host(0, 1, 0, hold=2)
        for _ in range(100000):
            if self.descriptors == completed:
                break
            await self.tick()
        else:
            raise AssertionError('TMA_TIMEOUT waiting for completion')
        if not check_memory:
            return
        if full_scan:
            await self.scan()
        else:
            for _, da in prefix:
                await self.host(0, 1, da, hold=self.random(6))
            for guard in range(16):
                await self.host(0, 1, ((guard*251 + self.descriptors*73) % 4096)*2)

    def report(self, **extra):
        data = dict(descriptors=self.descriptors, read_checks=self.read_checks,
                    write_checks=self.write_checks, memory_checks=self.memory_checks,
                    scenarios={key: sorted(values) for key, values in self.bins.items()},
                    busy_blocked=self.blocked, long_hold=self.long_hold, **extra)
        Path(os.environ['TMA_REPORT']).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


@cocotb.test(timeout_time=100, timeout_unit='ms')
async def tensor_regression(dut):
    bench = Bench(dut, int(os.environ['TMA_SEED']))
    for _ in range(4):
        await FallingEdge(dut.clk)
    while not bench.get('init_done'):
        await bench.tick()
    if os.environ['TMA_CORRUPT'] == '1':
        try:
            await bench.descriptor(shape(0, 0, 0, 1, 1), check_memory=False)
        except DmaCorruption as error:
            bench.report(corruption_detected=str(error))
            return
        raise AssertionError('TMA_CORRUPTION_MISSED')

    for word in range(4096):
        await bench.host(1, 1, word*2, word ^ 0xca71, word % 6)
    await bench.scan()
    await bench.host(1, 0, 0, 0xa55a)
    await bench.host(0, 0, 0, hold=850)
    for write, dst, addr in [(0, 0, 1), (1, 0, SOURCE_BYTES), (0, 1, DEST_BYTES), (1, 1, 1)]:
        await bench.host(write, dst, addr)
    for bank in range(4):
        for family in range(5):
            await bench.descriptor(shape(family, bank, (bank+family) % 4))
    for desc in (replace(shape(0, 0, 0, 32, 32), src_base=0x7f0, dst_base=0),
                 replace(shape(1, 3, 0, 32, 32), src_base=0x03fff800, dst_base=0),
                 replace(shape(2, 2, 1, 8, 16), src_base=0x020007fa), shape(3, 3, 0, 32, 8)):
        await bench.descriptor(desc, full_scan=True)
    for offset in range(4):
        await bench.descriptor(replace(shape(0, 1, offset, 1, 1), src_base=0x01000400+offset*2))
    for desc in (replace(shape(0, 0, 0, 1, 8), dst_col_stride=0), shape(0, 0, 0, 0, 4),
                 replace(shape(0, 0, 0, 1, 4), src_base=1), replace(shape(0, 0, 0, 1, 1), src_row_stride=1),
                 replace(shape(0, 0, 0, 1, 2), dst_base=8190), replace(shape(0, 3, 3, 1, 2), src_base=0x03fffffe)):
        await bench.descriptor(desc)
    for _ in range(12):
        family, bank, offset = bench.random(5), bench.random(4), bench.random(4)
        row, word = bench.random(5), bench.random(1025)
        await bench.descriptor(shape(family, bank, offset, 1+bench.random(8), 1+bench.random(8), row, word))
    for _ in range(1000):
        await bench.tick()
    await bench.scan()
    assert not (bench.active or bench.reads or bench.writes or bench.stalled), 'TMA_PENDING'
    assert bench.maintenance is None, 'TMA_MAINT_PENDING'
    assert (bench.descriptors, bench.read_checks, bench.write_checks, bench.memory_checks) == (46, 2937, 2937, 25797)
    for key, bins in {'bank_family': 20, 'offset': 4, 'status': 4, 'size': 5, 'stall': 3}.items():
        assert len(bench.bins[key]) == bins, f'TMA_SCENARIO_GAP {key}'
    assert bench.blocked and bench.long_hold, 'TMA_SCENARIO_GAP busy/refresh'
    bench.report()
