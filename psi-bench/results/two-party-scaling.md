# two-party-scaling

| experiment | runs ok | correct | wall s (median ±95% CI) | CPU s | peak RSS MB | comm MB | online MB |
|---|---|---|---|---|---|---|---|
| volepsi 1024 vs 262144 none t1 32bit | 3/3 | yes | 0.149 ±0.002 | 0.15 ±0.01 | 15 ±0 | 2.72 | - |
| volepsi 1024 vs 4194304 none t1 32bit | 3/3 | yes | 1.544 ±0.074 | 1.57 ±0.06 | 135 ±1 | 38.18 | - |
| pepsi-e2e[hash-index] 1024 vs 262144 none t6 32bit | 3/3 | yes | 3.470 ±0.276 | 16.82 ±0.21 | 376 ±12 | 6.40 | 5.39 |
| pepsi-e2e[hash-index] 1024 vs 4194304 none t6 32bit | 3/3 | yes | 30.892 ±2.976 | 175.91 ±15.49 | 3251 ±6 | 6.40 | 5.38 |
