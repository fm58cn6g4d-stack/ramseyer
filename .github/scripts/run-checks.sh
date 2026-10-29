#!/usr/bin/env bash
# PR checks for ramseyer: install, unit tests, and the gate's own tests. The accuracy gates (scripts/m*_gate.py)
# need about 10 GB of downloaded data under var/ and are not run here; a PR that changes behaviour reports their
# results, and the measured baselines under tests/oracle/ show any regression in review.
# Usage (from the repo root): bash .github/scripts/run-checks.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

echo "::group::install"
python3 -m venv "${RUNNER_TEMP:-/tmp}/venv"
PY="${RUNNER_TEMP:-/tmp}/venv/bin/python"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -e '.[dev]'
echo "::endgroup::"

echo "::group::unit tests"
"$PY" -m pytest -q
echo "::endgroup::"

echo "::group::merge gate tests"
python3 .github/scripts/test_agent_gate.py
echo "::endgroup::"

if ! git diff --quiet; then
  echo "::error::A check modified tracked files:"; git diff --stat; exit 1
fi
echo "All checks passed."
