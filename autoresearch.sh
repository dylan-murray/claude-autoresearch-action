#!/bin/bash
set -euo pipefail

# Count TODO occurrences in the corpus
grep -rI --exclude-dir='__pycache__' -c 'TODO' fixtures/todo-corpus/ 2>/dev/null | awk -F: '{s+=$2} END {print "METRIC todo_count=" (s+0)}'

# Count .py files
py_count=$(ls fixtures/todo-corpus/*.py 2>/dev/null | wc -l)
echo "METRIC py_files=${py_count}"
