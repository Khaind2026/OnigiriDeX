#!/usr/bin/env bash
# Build an SM-F741N AP candidate after the staged b6q framework work is ready.
set -Eeuo pipefail
SRC_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: bash scripts/build_odin_b6q.sh [AP_F741N*.tar.md5]"
    echo "Builds b6q super (if needed), then packages it in the verified F741N AP container."
    echo "Output is an experimental AP candidate; not validated for flashing."
    exit 0
fi
STOCK_AP="${1:-}"
if [[ -z "$STOCK_AP" ]]; then
    STOCK_DIR="$SRC_DIR/out/odin/SM-F741N_SKC"
    mapfile -t APS < <(find "$STOCK_DIR" -maxdepth 1 -type f -name 'AP_F741N*.tar.md5' -print 2>/dev/null | sort)
    if (( ${#APS[@]} != 1 )); then
        echo "Expected exactly one imported AP_F741N*.tar.md5 in $STOCK_DIR" >&2
        echo "Import firmware first with scripts/import_duykhaidex_f741n.py" >&2
        exit 1
    fi
    STOCK_AP="${APS[0]}"
fi
[[ -f "$STOCK_AP" ]] || { echo "Missing stock F741N AP: $STOCK_AP" >&2; exit 1; }
if [[ "$STOCK_AP" == *AP_F956N* ]]; then
    echo "Refusing Fold6 AP: Odin boot chain must remain F741N" >&2
    exit 1
fi
SUPER="$SRC_DIR/out/b6q/build/DuyKhaiDeX_F741N_SUPER_PREVIEW_NOT_FOR_FLASH.img"
if [[ ! -s "$SUPER" ]]; then
    echo "Building and verifying the F741N-geometry super image first..."
    bash "$SRC_DIR/scripts/build_super_b6q.sh" --build
fi
python3 "$SRC_DIR/scripts/build_odin_b6q.py" "$STOCK_AP" "$SUPER" \
    --output "$SRC_DIR/out/DuyKhaiDeX_AP_SM-F741N_CANDIDATE_NOT_FLASH_READY.tar.md5"
