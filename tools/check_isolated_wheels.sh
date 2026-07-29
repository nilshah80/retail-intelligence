#!/usr/bin/env sh
# Optional POSIX convenience wrapper. Windows runs:
#   py -3 tools/check_isolated_wheels.py
set -eu
exec "${PYTHON:-python3}" "$(dirname "$0")/check_isolated_wheels.py" "$@"
