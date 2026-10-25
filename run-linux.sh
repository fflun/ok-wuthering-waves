#!/usr/bin/env bash
set -euo pipefail
bundle_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_python="${OKWW_PYTHON:-$bundle_root/.venv/bin/python}"
task_root="$bundle_root/workspace/wuwa-linux"
export OKWW_INSTALLED_RUNTIME="$task_root"
export PYTHONPATH="$task_root/code:$task_root/vendor"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
case "${1:-help}" in
  help) exec "$task_python" "$task_root/code/main_cloud_daily.py" --help;;
  preflight) exec "$task_python" "$task_root/code/linux_preflight.py";;
  *) echo 'Use help or preflight. Configure deployment layout, account binding and supervised acceptance before game execution.' >&2; exit 2;;
esac
