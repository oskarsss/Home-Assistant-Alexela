#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 GITHUB_USERNAME REPOSITORY_NAME" >&2
  echo "Example: $0 oskars alexela-home-assistant" >&2
  exit 2
fi

USER="$1"
REPO="$2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/custom_components/alexela/manifest.json"

python3 - "$MANIFEST" "$USER" "$REPO" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
user = sys.argv[2]
repo = sys.argv[3]

data = json.loads(path.read_text())
data['documentation'] = f'https://github.com/{user}/{repo}'
data['issue_tracker'] = f'https://github.com/{user}/{repo}/issues'
data['codeowners'] = [f'@{user}']
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
PY

"$ROOT/scripts/fetch-brand-assets.sh"

echo
echo "Repository metadata prepared for https://github.com/$USER/$REPO"
echo "Review manifest.json and then commit the repository."
