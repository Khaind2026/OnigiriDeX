#!/usr/bin/env bash
# Build Odin AP packages for both Z Flip5 models with exact pinned firmware.
# Usage: bash scripts/build_dk_both_flip5.sh B.zip N.zip Fold5.zip [S24.zip]
set -eo pipefail

if (( $# < 3 || $# > 4 )); then
  echo "Usage: bash scripts/build_dk_both_flip5.sh F731B.zip F731N.zip F946B.zip [S921B.zip]" >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
B_ZIP="$(realpath -e "$1")"
N_ZIP="$(realpath -e "$2")"
DONOR_ZIP="$(realpath -e "$3")"
S24_ZIP=""
if (( $# == 4 )); then S24_ZIP="$(realpath -e "$4")"; fi
cd "$ROOT"

[ "$(uname -s)" = Linux ] || { echo "Linux required (Windows: use WSL2)." >&2; exit 1; }
FREE_GIB="$(df -Pk "$ROOT" | awk 'NR==2 {print int($4/1048576)}')"
echo "Free disk space: $FREE_GIB GiB. Plan for at least 150 GiB."
if (( FREE_GIB < 150 )); then
  echo "At least 150 GiB free is required by this dual-build helper. Use a larger Linux filesystem." >&2
  exit 1
fi

# Eureka always consumes these Android 15 assets. Do not silently disable the module.
EAD_SOURCE="$ROOT/out/fw/SM-S921B_XXV/software"
if [ -d "$EAD_SOURCE" ]; then
  PYTHONPATH="$ROOT/scripts" python3 - "$EAD_SOURCE" <<'PYVERIFY'
import sys
from pathlib import Path
from extract_adaptive_display import verify_imported_software
verify_imported_software(Path(sys.argv[1]))
PYVERIFY
elif [ -z "$S24_ZIP" ]; then
  echo "S921BXXS9BYH1 ZIP is required as argument 4 unless verified S24 software is already extracted." >&2
  exit 1
fi

# Fail before downloads/compilation if native commands are unavailable.
MISSING=()
for TOOL in bc brotli clang cmake getfattr java javac lz4 pcre2test protoc \
    python3 zstd make ninja pkg-config cpio rsync flex bison; do
  command -v "$TOOL" >/dev/null 2>&1 || MISSING+=("$TOOL")
done
if (( ${#MISSING[@]} )); then
  echo "Missing native commands: ${MISSING[*]}" >&2
  echo "On Debian 13 run: sudo bash scripts/setup_dk_debian.sh" >&2
  exit 1
fi
for MODULE in android-tools apktool erofs-utils samloader signapk; do
  if [ ! -e "$ROOT/external/$MODULE/.git" ]; then
    echo "Missing submodule $MODULE. Run git submodule update --init --recursive." >&2
    exit 1
  fi
done

echo "[1/7] Build dependencies"
source ./buildenv.sh SM-F731B
onigiri build_dependencies

import_once() {
  local ROLE="$1" ZIP="$2" DEST="$3"
  if [ -f "$DEST/.downloaded" ]; then
    echo "Already imported $ROLE; extract_fw verifies pinned firmware."
  elif [ -e "$DEST" ]; then
    echo "Incomplete import directory $DEST; investigate before retrying." >&2
    exit 1
  else
    python3 scripts/import_fw.py "$ROLE" "$ZIP"
  fi
}

echo "[2/7] Import exact firmware archives (MD5 checked)"
import_once SM-F731B "$B_ZIP" out/odin/SM-F731B_XXV
import_once SM-F731N "$N_ZIP" out/odin/SM-F731N_KOO
import_once donor "$DONOR_ZIP" out/odin/SM-F946B_XXV

echo "[3/7] Extract international Flip5 and donor firmware"
onigiri extract_fw
if [ ! -d "$EAD_SOURCE" ]; then
  python3 scripts/extract_adaptive_display.py "$S24_ZIP"
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
