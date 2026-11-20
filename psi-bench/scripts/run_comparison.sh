#!/usr/bin/env bash
# Run the three comparison suites back to back. Re-runnable: --skip-done only repeats what is missing.
# For cleaner numbers stop other CPU-heavy containers (e.g. Airflow) first.
cd "$(dirname "$0")/.."
for s in two_party_32bit two_party_128bit multi_party; do
  ./psibench suite "suites/$s.json" --skip-done
done
echo "ALL SUITES FINISHED"
