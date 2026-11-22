#!/usr/bin/env bash
# Install or upgrade the project kit in a repository (macOS/Linux launcher for install.py).
#
#   ./install.sh [TARGET] [--global] [--dry-run]
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [[ -z "$PY" ]]; then
  echo "Python 3.8 or newer was not found on PATH. Install it and run this again." >&2
  exit 1
fi

exec "$PY" "$KIT_ROOT/install.py" --python-cmd "$PY" "$@"
