#!/usr/bin/env bash
# Build Odin AP packages for both Z Flip5 models with exact pinned firmware.
# Usage: bash scripts/build_dk_both_flip5.sh B_folder N_folder Fold5_folder [S24.zip]
set -eo pipefail

if (( $# < 3 || $# > 4 )); then
  echo "Usage: bash scripts/build_dk_both_flip5.sh <F731B-folder-or-ZIP> <F731N-folder-or-ZIP> <F946B-folder-or-ZIP> [S921B.zip]" >&2
  exit 2
fi
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
B_INPUT="$(realpath -e "$1")"
N_INPUT="$(realpath -e "$2")"
DONOR_INPUT="$(realpath -e "$3")"
S24_ZIP=""
if (( $# == 4 )); then S24_ZIP="$(realpath -e "$4")"; fi

[ "$(uname -s)" = Linux ] || { echo "Linux required (Windows: use WSL2)." >&2; exit 1; }
FREE_GIB="$(df -Pk "$ROOT" | awk 'NR==2 {printf "%.0f", $4/1048576}')"
echo "Free disk space: $FREE_GIB GiB. Plan for at least 150 GiB."
if (( FREE_GIB < 120 )); then
  echo "WARNING: insufficient disk space may interrupt the build." >&2
fi

echo "[1/7] Build dependencies"
source ./buildenv.sh SM-F731B
onigiri build_dependencies

import_once() {
  local ROLE="$1" INPUT="$2" DEST="$3"
  if [ -f "$DEST/.downloaded" ]; then
    echo "Already imported $ROLE; extract_fw verifies pinned firmware."
  elif [ -e "$DEST" ]; then
    echo "Incomplete import directory $DEST; investigate before retrying." >&2
    exit 1
  else
    if [ -d "$INPUT" ]; then
      python3 scripts/import_fw_dir.py "$ROLE" "$INPUT"
    else
      python3 scripts/import_fw.py "$ROLE" "$INPUT"
    fi
  fi
}

echo "[2/7] Import exact firmware ZIPs or extracted Odin directories (MD5 checked)"
import_once SM-F731B "$B_INPUT" out/odin/SM-F731B_XXV
import_once SM-F731N "$N_INPUT" out/odin/SM-F731N_KOO
import_once donor "$DONOR_INPUT" out/odin/SM-F946B_XXV

echo "[3/7] Extract international Flip5 and donor firmware"
onigiri extract_fw
onigiri extract_fw --ignore-source --ignore-target SM-F946B/XXV
if [ -n "$S24_ZIP" ]; then
  if [ ! -f out/fw/SM-S921B_XXV/software/manifest.json ]; then
    python3 scripts/extract_adaptive_display.py "$S24_ZIP"
  fi
else
  echo "Optional S24 display-colour firmware not supplied."
fi

echo "[4/7] Build shared kernel"
onigiri build_kernel
echo "[5/7] Build SM-F731B Odin AP"
onigiri build_odin

echo "[6/7] Build SM-F731N Odin AP"
source ./buildenv.sh SM-F731N
onigiri extract_fw
onigiri build_odin

echo "[7/7] Verify presence and list output hashes"
for MODEL in SM-F731B SM-F731N; do
  FOUND=0
  for AP in out/Onigiri_AP_"$MODEL"_*.tar.md5; do
    [ -f "$AP" ] || continue
    FOUND=1
    ls -lh "$AP"
    sha256sum "$AP"
  done
  [ "$FOUND" = 1 ] || { echo "Missing AP output for $MODEL" >&2; exit 1; }
done
echo "Done: independent AP files for SM-F731B and SM-F731N; never cross-flash."
