# Autoresearch: Reduce TODO Count in fixtures/todo-corpus/

## Objective
Reduce the number of occurrences of the string "TODO" in any file under `fixtures/todo-corpus/`.
All `.py` files in that directory must remain parseable by `python3 -m py_compile`.

## Metrics
- **Primary**: `todo_count` (unitless, lower is better) — total `TODO` occurrences in `fixtures/todo-corpus/`
- **Secondary**: `py_files` — number of `.py` files in the directory (should stay constant)

## How to Run
`./autoresearch.sh`

## Files in Scope
- `fixtures/todo-corpus/sample.py` — target file containing TODO comments and docstring references
- `fixtures/todo-corpus/README.md` — documentation file that also contains "TODO" occurrences

## Off Limits
- Any file outside `fixtures/todo-corpus/`
- Deleting `.py` files (they must remain parseable)

## Constraints
- All `.py` files under `fixtures/todo-corpus/` must pass `python3 -m py_compile`
- `.py` files must not be deleted

## What's Been Tried
*Baseline established.*
