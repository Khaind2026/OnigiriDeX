#!/usr/bin/env bash
# Offline check of the stock-boot engineering AP reported for BYGB.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/out/tools/bin:$PATH"
build=out/b6q/build
stock=out/b6q/analysis/f741n-stock-boot-chain
ap="$build/DuyKhaiDeX_F741N_F956N_ENGINEERING_AP_NOT_FOR_FLASH.tar.md5"
expected=1cdcb630c422038b6d74d69af89067fe2af81888feee72e12e992659172f7e5f
printf '%s  %s\n' "$expected" "$ap" | sha256sum -c -
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
