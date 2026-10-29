# Bank-layout comparison

Same four-lane logical requests, data, clock, and response-ready schedule.
Values below are mean request-issue spans for one four-word batch, with all responses ready.

| Pattern | Linear | XOR shift 3 | XOR shift 4 | XOR shift 5 |
| --- | --- | --- | --- | --- |
| 32x32 row, row stride 32 words | 1.000 | 1.000 | 1.000 | 1.000 |
| 8x8 column, row stride 8 words | 4.000 | 1.000 | 2.000 | 4.000 |
| 16x16 column, row stride 16 words | 4.000 | 2.000 | 1.000 | 2.000 |
| 32x32 column, row stride 32 words | 4.000 | 4.000 | 2.000 | 1.000 |
| 8x8 column, row stride 12 words | 4.000 | 1.500 | 2.000 | 2.750 |
| 8x8 column, row stride 20 words | 4.000 | 1.500 | 1.500 | 2.000 |
| 8x8 column, row stride 36 words | 4.000 | 2.000 | 2.000 | 1.250 |
| diagonal_stride33 | 1.000 | 1.000 | 1.000 | 4.000 |
| buffer_boundary | 1.000 | 2.000 | 2.000 | 2.000 |

A four-word batch completes one cycle after its request-issue span in this all-ready model.
For 32-word column stride, shift 5 changes issue span 4 -> 1 and completion span 5 -> 2.
The stride-33 diagonal regresses: issue span 1 -> 4, completion span 2 -> 5.
These are four-lane scratchpad measurements, not single-stream copy or SDRAM speedups.
