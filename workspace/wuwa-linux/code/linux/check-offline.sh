#!/bin/sh
# Import-only check; this command never launches the browser or an OK task.
set -eu
stage=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export PYTHONPATH="$stage/code:$stage/vendor"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p "$stage/probe-state"
cd "$stage/probe-state"
exec "$stage/.venv/bin/python" "$stage/code/linux/offline_probe.py"
