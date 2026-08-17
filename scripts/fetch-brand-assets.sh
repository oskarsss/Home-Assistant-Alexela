#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# Current Alexela brand image served by Alexela Latvia's own website.
SOURCE='https://www.alexela.lv/themes/public/images/Alexela_Duallogo_fallback.png'

echo "Downloading official Alexela brand image..."
curl --fail --location --silent --show-error "$SOURCE" -o "$TMP"

# Basic PNG signature check, to avoid committing an HTML error page as an icon.
python3 - "$TMP" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
if p.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
    raise SystemExit('Downloaded file is not a PNG; Alexela may have changed the asset URL.')
PY

mkdir -p "$ROOT/custom_components/alexela/brand" "$ROOT/brand"

# The official asset is square and works as both an integration icon and logo.
for dir in "$ROOT/custom_components/alexela/brand" "$ROOT/brand"; do
  cp "$TMP" "$dir/icon.png"
  cp "$TMP" "$dir/dark_icon.png"
  cp "$TMP" "$dir/logo.png"
  cp "$TMP" "$dir/dark_logo.png"
done

echo "Brand assets updated from: $SOURCE"
echo "Files written to:"
echo "  custom_components/alexela/brand/"
echo "  brand/"
