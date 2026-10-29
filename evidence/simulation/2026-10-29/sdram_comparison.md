# SDRAM baseline comparison

Pin-level simulation at 50 MHz, BL1, close-page policy, identical refresh start phase.
These are simulated core cycles, not measured hardware bandwidth.

| Workload | Serialized cycles | Pipelined cycles | Ratio |
| --- | --- | --- | --- |
| last_word | 17 | 18 | 0.944x |
| row_crossing | 257 | 213 | 1.207x |
| copy32 | 16523 | 13539 | 1.220x |
| transpose32 | 16523 | 13539 | 1.220x |
| padded | 2064 | 1693 | 1.219x |
| column_gather | 4130 | 3387 | 1.219x |
| broadcast | 516 | 427 | 1.208x |
| small_transpose | 241 | 200 | 1.205x |
