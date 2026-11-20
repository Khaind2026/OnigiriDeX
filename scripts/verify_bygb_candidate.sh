#!/usr/bin/env bash
# Offline check of the stock-boot engineering AP reported for BYGB.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/out/tools/bin:$PATH"
build=out/b6q/build
stock=out/b6q/analysis/f741n-stock-boot-chain
default_ap="$build/DuyKhaiDeX_F741N_F956N_ENGINEERING_AP_NOT_FOR_FLASH.tar.md5"
expected=1cdcb630c422038b6d74d69af89067fe2af81888feee72e12e992659172f7e5f
expected_bytes=9412352090
ap=
declare -A checked=()
check_file() {
    local candidate=$1 size identity digest
    [[ -f "$candidate" && -r "$candidate" ]] || return 1
    size=$(stat -Lc %s -- "$candidate") || return 1
    [[ $size == "$expected_bytes" ]] || return 1
    identity=$(stat -Lc '%d:%i' -- "$candidate") || return 1
    [[ ! ${checked[$identity]+seen} ]] || return 1
    checked[$identity]=1
    printf 'Checking SHA-256: %s\n' "$candidate" >&2
    digest=$(sha256sum < "$candidate") || return 1
    [[ ${digest%% *} == "$expected" ]] || return 1
    ap=$candidate
}
if (( $# > 1 )); then
    echo "Usage: bash scripts/verify_bygb_candidate.sh [absolute-AP-path]" >&2
    exit 2
elif (( $# == 1 )); then
    check_file "$1" || { echo "Specified file is unavailable or differs from the recorded AP" >&2; exit 1; }
elif ! check_file "$default_ap"; then
    for root in "$PWD/out" "$HOME" /mnt/[a-z]; do
        [[ -d "$root" ]] || continue
        echo "Searching for the recorded AP under $root" >&2
        while IFS= read -r -d '' candidate; do
            if check_file "$candidate"; then break; fi
        done < <(find "$root" -xdev -type f -size "${expected_bytes}c" -print0)
        [[ -z "$ap" ]] || break
    done
fi
if [[ -z "$ap" ]]; then
    echo "Recorded AP not found in readable search locations. For another mount pass its full file path." >&2
    exit 1
fi
printf 'Verified AP SHA-256: %s\n' "$ap"
for name in boot init_boot vendor_boot dtbo recovery vbmeta_system; do
    packed=$(tar -xOf "$ap" "$name.img.lz4" | lz4 -dc | sha256sum)
    staged=$(sha256sum "$stock/$name.img")
    if [[ ${packed%% *} != ${staged%% *} ]]; then
        echo "Stock image comparison FAILED: $name" >&2
        exit 1
    fi
    echo "Matches staged F741N image: $name"
done
for tool in simg2img lpunpack avbtool; do
    command -v "$tool" >/dev/null || { echo "Missing host tool: $tool" >&2; exit 2; }
done
mkdir -p "$build"
tmp=$(mktemp -d "$build/.verify-ap.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
mkdir "$tmp/partitions"
tar -xOf "$ap" super.img.lz4 | lz4 -dc > "$tmp/super.sparse"
simg2img "$tmp/super.sparse" "$tmp/super.raw"
rm "$tmp/super.sparse"
lpunpack "$tmp/super.raw" "$tmp/partitions"
rm "$tmp/super.raw"
tar -xOf "$ap" vbmeta_system.img.lz4 | lz4 -dc > "$tmp/partitions/vbmeta_system.img"
echo "Checking AP dynamic partitions against the packaged vbmeta_system descriptors"
avbtool verify_image --image "$tmp/partitions/vbmeta_system.img"
echo "AP vbmeta_system check completed; BL trust and on-device boot remain untested."
