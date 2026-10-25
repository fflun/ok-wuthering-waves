#!/bin/sh
# Ends after blank-page, synthetic OCR/template verification; never starts game tasks.
set -eu
stage=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export PYTHONPATH="$stage/code:$stage/vendor"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p "$stage/probe-state"
cd "$stage/probe-state"
exec nice -n 10 "$stage/.venv/bin/python" "$stage/code/main_cloud_linux.py" --probe
