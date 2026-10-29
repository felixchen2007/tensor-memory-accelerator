# Four-word read-prefetch comparison

Simulated descriptors; identical refresh start phase.

| Workload | Pipelined BL1 cycles | Pipelined BL4 cycles | Ratio | BL1 / BL4 READ commands | BL1 / BL4 data beats |
| --- | --- | --- | --- | --- | --- |
| last_word | 18 | 21 | 0.857x | 1 / 1 | 1 / 4 |
| row_crossing | 213 | 93 | 2.290x | 16 / 4 | 16 / 16 |
| copy32 | 13539 | 5733 | 2.362x | 1024 / 256 | 1024 / 1024 |
| transpose32 | 13539 | 5733 | 2.362x | 1024 / 256 | 1024 / 1024 |
| padded | 1693 | 721 | 2.348x | 128 / 32 | 128 / 128 |
| column_gather | 3387 | 4167 | 0.813x | 256 / 256 | 256 / 1024 |
| broadcast | 427 | 83 | 5.145x | 32 / 1 | 32 / 4 |
| small_transpose | 200 | 105 | 1.905x | 15 / 5 | 15 / 20 |
