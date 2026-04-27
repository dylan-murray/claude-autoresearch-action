#!/bin/bash
set -euo pipefail

# Run existing pytest tests to ensure digest_event still behaves correctly.
# Only show failures — suppress verbose success output.
cd "$(dirname "$0")"

# First verify there are no syntax errors (fast check)
python3 -c "import py_compile; py_compile.compile('scripts/pi_rpc_driver.py', doraise=True)"

# Then run the tests
python3 -m pytest tests/test_pi_rpc_driver.py -x --tb=short -q 2>&1 | tail -50
