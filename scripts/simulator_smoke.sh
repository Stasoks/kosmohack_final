#!/usr/bin/env bash
set -Eeuo pipefail

python_bin="${PYTHON_BIN:-python}"
"${python_bin}" scripts/simulator_smoke.py
