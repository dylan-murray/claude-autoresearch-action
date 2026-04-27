# todo-corpus

Smoke-test fixture for `claude-autoresearch-action`.

The self-test workflow uses an explicit goal to optimize:

- **Goal:** reduce outstanding comment count under `fixtures/todo-corpus/`
- **Benchmark:** `grep -rc 'FIXME|HACK' fixtures/todo-corpus/ | awk -F: '{s+=$2} END {print "METRIC todo_count=" (s+0)}'`
- **Guard:** every `.py` in `fixtures/todo-corpus/` must still parse via `python3 -m py_compile`
- **Direction:** `lower_is_better`
- **Scope:** `fixtures/todo-corpus/**`

The autoresearch loop should remove outstanding comments one iteration at a time
while keeping the surrounding code intact (the guard rejects any iteration
that breaks Python parsing). After enough iterations, the count should
reach zero or the loop should plateau.

This is a deliberately simple smoke goal — the kind of thing that takes 1-2
seconds to measure, with a binary outcome each iteration, used to validate
the loop end-to-end before pointing it at real-repo metrics.
