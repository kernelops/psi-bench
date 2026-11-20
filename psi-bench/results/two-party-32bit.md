# two-party-32bit

| experiment | runs ok | correct | wall s (median ±95% CI) | CPU s | peak RSS MB | comm MB | online MB |
|---|---|---|---|---|---|---|---|
| volepsi 1024 vs 65536 none t1 32bit | 5/5 | yes | 0.071 ±0.003 | 0.07 ±0.00 | 10 ±0 | 0.95 | - |
| volepsi 1024 vs 1048576 none t1 32bit | 5/5 | yes | 0.413 ±0.016 | 0.42 ±0.02 | 39 ±0 | 9.81 | - |
| volepsi 4096 vs 1048576 none t1 32bit | 5/5 | yes | 0.419 ±0.013 | 0.43 ±0.01 | 39 ±0 | 9.89 | - |
| volepsi 4096 vs 4096 none t1 32bit | 5/5 | yes | 0.056 ±0.006 | 0.05 ±0.01 | 10 ±0 | 0.47 | - |
| volepsi 65536 vs 65536 none t1 32bit | 5/5 | yes | 0.150 ±0.006 | 0.16 ±0.01 | 31 ±0 | 2.36 | - |
| pepsi-e2e[hash-index] 1024 vs 65536 none t6 32bit | 5/5 | yes | 1.473 ±0.172 | 5.39 ±0.02 | 210 ±4 | 6.39 | 5.39 |
| pepsi-e2e[hash-index] 1024 vs 1048576 none t6 32bit | 5/5 | yes | 9.481 ±0.184 | 51.16 ±1.28 | 984 ±6 | 6.40 | 5.38 |
| pepsi-e2e[hash-index] 4096 vs 1048576 none t6 32bit | 5/5 | yes | 8.955 ±0.533 | 49.22 ±2.20 | 985 ±5 | 6.40 | 5.38 |
| pepsi-e2e[hash-index] 4096 vs 4096 none t6 32bit | 5/5 | yes | 0.606 ±0.112 | 1.35 ±0.06 | 127 ±4 | 6.39 | 5.38 |
| pepsi-e2e[hash-index] 65536 vs 65536 none t6 32bit | 5/5 | yes | 3.816 ±0.106 | 13.32 ±0.24 | 417 ±3 | 47.39 | 46.34 |
| pepsi-e2e[paper-literal] 1024 vs 1048576 none t6 32bit | 5/5 | yes | 9.956 ±0.259 | 55.28 ±0.79 | 904 ±2 | 5.82 | 4.80 |
| pepsi-e2e[paper-literal] 4096 vs 1048576 none t6 32bit | 5/5 | NO (5/5 wrong) | 9.882 ±0.633 | 55.36 ±3.37 | 902 ±4 | 5.82 | 4.80 |
| pepsi-e2e[hash-index] 1024 vs 65536 none t1 32bit | 3/3 | yes | 5.263 ±0.190 | 5.26 ±0.17 | 136 ±1 | 6.40 | 5.38 |
| pepsi-e2e[hash-index] 1024 vs 1048576 none t1 32bit | 3/3 | yes | 52.492 ±3.625 | 52.45 ±3.60 | 906 ±0 | 6.41 | 5.39 |
| volepsi 1024 vs 1048576 wan t1 32bit | 5/5 | yes | 2.596 ±0.010 | 0.45 ±0.01 | 39 ±0 | 9.88 | - |
| volepsi 65536 vs 65536 wan t1 32bit | 5/5 | yes | 2.143 ±0.004 | 0.18 ±0.00 | 31 ±0 | 2.41 | - |
| pepsi-e2e[hash-index] 1024 vs 1048576 wan t6 32bit | 5/5 | yes | 11.892 ±0.848 | 57.82 ±5.20 | 985 ±3 | 6.46 | 5.38 |
| pepsi-e2e[hash-index] 65536 vs 65536 wan t6 32bit | 5/5 | yes | 7.117 ±0.332 | 13.19 ±1.14 | 417 ±3 | 47.55 | 46.33 |
