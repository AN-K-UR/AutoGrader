#!/usr/bin/env bash
# Grades every sample through the real agent and writes reports/samples/.
# Nothing here is hard-coded: delete that directory and this recreates it.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=.venv/bin/python
OUTPUT=reports/samples
mkdir -p "$OUTPUT"

for source in submissions/examples/add_*.c; do
    "$PYTHON" main.py grade --source "$source" --config config/rules.json --output "$OUTPUT" | head -1
done
for source in submissions/examples/sort_*.c; do
    "$PYTHON" main.py grade --source "$source" --config config/rules_sort.json --output "$OUTPUT" | head -1
done
"$PYTHON" scripts/summarize_reports.py "$OUTPUT" > "$OUTPUT/SUMMARY.md"
echo "Summary written to $OUTPUT/SUMMARY.md"
