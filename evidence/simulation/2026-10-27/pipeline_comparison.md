# Paired transfer-engine measurements

Both engines use identical data and per-transaction service delays.
Ratios compare this project's serialized and pipelined RTL; no hardware frequency or board bandwidth is measured.

| Case | Timing mode | Serialized cycles | Pipelined cycles | Speedup |
| --- | --- | --- | --- | --- |
| single_word_minimum_latency | 0 | 6 | 7 | 0.857x |
| copy_32x32_minimum_latency | 0 | 5121 | 1030 | 4.972x |
| copy_32x32_variable_latency | 2 | 15385 | 6227 | 2.471x |
| copy_8x8_minimum_latency | 0 | 321 | 70 | 4.586x |
| copy_16x16_minimum_latency | 0 | 1281 | 262 | 4.889x |
| copy_8x32_minimum_latency | 0 | 1281 | 262 | 4.889x |
| copy_32x8_minimum_latency | 0 | 1281 | 262 | 4.889x |
| transpose_32x32_minimum_latency | 0 | 5121 | 1030 | 4.972x |

Mode 0: always-ready requests and next-cycle responses.
Mode 2: deterministic transaction-indexed request gaps and response delays.
Single-word transfers expose pipeline startup/drain overhead.
