# two-party-128bit

| experiment | runs ok | correct | wall s (median ±95% CI) | CPU s | peak RSS MB | comm MB | online MB |
|---|---|---|---|---|---|---|---|
| volepsi 1024 vs 65536 none t1 | 3/3 | yes | 0.082 ±0.005 | 0.08 ±0.01 | 10 ±0 | 0.95 | - |
| volepsi 1024 vs 1048576 none t1 | 3/3 | yes | 0.547 ±0.020 | 0.56 ±0.03 | 39 ±1 | 9.81 | - |
| volepsi 65536 vs 65536 none t1 | 3/3 | yes | 0.163 ±0.016 | 0.18 ±0.03 | 31 ±1 | 2.36 | - |
| pepsi-e2e[large] 1024 vs 65536 none t6 | 3/3 | yes | 4.914 ±0.344 | 19.96 ±1.12 | 698 ±19 | 30.60 | 27.63 |
| pepsi-e2e[large] 1024 vs 1048576 none t6 | 3/3 | yes | 32.662 ±4.536 | 181.43 ±18.82 | 2582 ±75 | 33.92 | 30.93 |
| pepsi-e2e[large] 65536 vs 65536 none t6 | 3/3 | yes | 14.183 ±0.526 | 47.15 ±1.32 | 1330 ±28 | 160.38 | 157.26 |
| pepsi-e2e[large] 1024 vs 65536 none t1 | 3/3 | yes | 19.166 ±0.477 | 19.19 ±0.47 | 402 ±0 | 30.61 | 27.63 |
