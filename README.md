# psi-bench

A reproducible benchmark and web UI for comparing three private set intersection protocols under the same conditions:

- **PEPSI** (USENIX Security 2024), unbalanced two-party PSI from homomorphic encryption
- **VOLE-PSI** (EUROCRYPT 2021), two-party PSI from OKVS and VOLE
- **BZS-MPSI** (ACM CCS 2024), multi-party PSI

```
psi-bench/    benchmark harness, web UI, experiment suites and results      (MIT, this repository)
pepsi/        RasoulAM/pepsi, plus the end-to-end driver in pepsi/e2e        (driver: MIT, see NOTICE)
volepsi/      ladnir/volepsi                                                 (MIT, original history kept)
BZS-MPSI/     orzcy/BZS-MPSI                                                 (MIT, original history kept)
```

The three protocol folders are the original projects with their commit history; see [NOTICE](NOTICE) for sources, licenses
and the papers to cite. What this repository adds is the harness that runs them side by side (`psi-bench/`) and an
end-to-end driver for PEPSI, whose released code only benchmarks synthetic data (`pepsi/e2e/`).

**Start here: [psi-bench/README.md](psi-bench/README.md)** for setup, usage, what is measured, the results and their limits.
