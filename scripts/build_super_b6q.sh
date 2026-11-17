#!/usr/bin/env bash
# Direct reuse of OnigiriDeX Flip5 EROFS -> lpmake -> lpunpack workflow for b6q.
# Engineering SUPER PREVIEW only. Not a flashable Odin AP.
set -Eeuo pipefail

SRC_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
export SRC_DIR OUT_DIR="$SRC_DIR/out"
export TOOLS_DIR="$OUT_DIR/tools"
export PATH="$TOOLS_DIR/bin:$PATH"
source "$SRC_DIR/target/b6q/config.sh"
export TARGET_DISABLE_AVB_SIGNING
WORK_DIR="$OUT_DIR/target/b6q/SM-F741N/work_dir"
export WORK_DIR
REPORT="$OUT_DIR/reports/f741n-f956n-super-metadata.json"
OUTPUT_DIR="$OUT_DIR/b6q/build"
# A second, separately named preview may be built after Settings branding.
# Never overwrite the original DeX-only super preview already verified.
if [[ -f "$WORK_DIR/.b6q-settings-patched" ]]; then
    OUTPUT="$OUTPUT_DIR/DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img"
else
    OUTPUT="$OUTPUT_DIR/DuyKhaiDeX_F741N_SUPER_PREVIEW_NOT_FOR_FLASH.img"
fi
PARTITIONS=(system product system_ext vendor odm vendor_dlkm system_dlkm)

if [[ "$#" == 1 && "$1" == --help ]]; then
    echo "Usage: bash scripts/build_super_b6q.sh [--build]"
    echo "No args = readiness check. --build = repack 7 EROFS images using b5q pipeline."
    echo "Produces only super PREVIEW; do not flash."
    exit 0
fi
if (( $# > 1 )) || [[ "$#" == 1 && "$1" != --build ]]; then
    echo "Invalid argument; use --help" >&2
    exit 2
fi
[[ -f "$WORK_DIR/.b6q-prepared" && -f "$WORK_DIR/.b6q-dex-patched" ]] || {
    echo "DeX port work tree not prepared/patched. Run bash scripts/port_b6q.sh all" >&2
    exit 1
}
[[ ! -e "$OUTPUT" ]] || { echo "Output already exists; refusing overwrite: $OUTPUT" >&2; exit 1; }
for part in system product system_ext vendor odm vendor_dlkm system_dlkm; do
    [[ -d "$WORK_DIR/$part" && -s "$WORK_DIR/configs/fs_config-$part" && -s "$WORK_DIR/configs/file_context-$part" ]] || {
        echo "Incomplete b6q work tree for $part" >&2
        exit 1
    }
done

# LP geometry MUST be read from real F741N stock, never guessed from Fold5/Fold6.
if ! GEOMETRY="$(python3 - "$REPORT" <<'PY'
import json,sys
j=json.load(open(sys.argv[1]))
devices=[x for x in j['devices'] if x.get('model')=='SM-F741N']
if len(devices)!=1 or devices[0].get('checksums_valid') is not True:
    raise SystemExit('Missing verified target F741N super metadata')
d=devices[0]
groups=[g for g in d['groups'] if g['name']=='qti_dynamic_partitions']
blocks=[b for b in d['block_devices'] if b['name']=='super']
parts={p['name'] for p in d['partitions']}
required={'system','product','system_ext','vendor','odm','vendor_dlkm','system_dlkm'}
geom=d['geometry']
if (len(groups)!=1 or len(blocks)!=1 or parts!=required or
        d['header_version']!='10.0' or geom['metadata_slots']!=2 or
        geom['metadata_max_size']<65536):
    raise SystemExit('Unexpected target F741N LP layout')
device=blocks[0]['size_bytes']
limit=groups[0]['maximum_bytes']
if not (0<limit<device<64*1024**3):
    raise SystemExit('Invalid target F741N super size')
print(device,limit)
PY
)"; then
    echo "Cannot read verified F741N LP metadata" >&2
    exit 1
fi
read -r SUPER_SIZE GROUP_LIMIT <<< "$GEOMETRY"
[[ "$SUPER_SIZE" =~ ^[0-9]+$ && "$GROUP_LIMIT" =~ ^[0-9]+$ ]] || exit 1
echo "DuyKhaiDeX — direct OnigiriDeX b5q-style super repack for b6q"
echo "F741N super bytes: $SUPER_SIZE; group bytes: $GROUP_LIMIT"
echo "Source: verified F956N system/product/system_ext + F741N hardware"
if (( $# == 0 )); then
    echo "PREFLIGHT PASS; run bash scripts/build_super_b6q.sh --build to create preview"
    exit 0
fi

for command in lpmake simg2img lpunpack mkfs.erofs cmp; do
    command -v "$command" >/dev/null || { echo "Missing build tool: $command" >&2; exit 1; }
done
mkdir -p "$OUTPUT_DIR"
STAGE="$(mktemp -d "$OUTPUT_DIR/.super-preview.XXXXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT

# Same builder as b5q. Explicitly disable test-key AVB signing in preview:
# actual F741N vbmeta/bootloader and rollback chain must be resolved first.
SUPER_COMMAND=(lpmake --metadata-size 65536 --super-name super --metadata-slots 2
    --device "super:$SUPER_SIZE" --group "qti_dynamic_partitions:$GROUP_LIMIT"
    --sparse --output "$STAGE/super.img")
OCCUPIED=0
for part in system product system_ext vendor odm vendor_dlkm system_dlkm; do
    echo "- Building b6q $part with scripts/build_fs_image.sh"
    "$SRC_DIR/scripts/build_fs_image.sh" erofs --no-avb -o "$STAGE/$part.img"         "$WORK_DIR/$part" "$WORK_DIR/configs/file_context-$part"         "$WORK_DIR/configs/fs_config-$part"
    SIZE="$(stat -c %s "$STAGE/$part.img")"
    (( SIZE > 0 )) || { echo "Invalid $part image" >&2; exit 1; }
    OCCUPIED=$((OCCUPIED + SIZE))
    (( OCCUPIED <= GROUP_LIMIT )) || {
        echo "Built images exceed actual F741N group limit" >&2; exit 1;
    }
    SUPER_COMMAND+=(--partition "$part:readonly:$SIZE:qti_dynamic_partitions"
                    --image "$part=$STAGE/$part.img")
done

echo "- Packing super.img using F741N's real geometry"
"${SUPER_COMMAND[@]}"
simg2img "$STAGE/super.img" "$STAGE/super.raw.img"
mkdir "$STAGE/unpacked"
echo "- Unpacking all 7 partitions in one pass (avoids repeated 13 GiB reads)"
lpunpack "$STAGE/super.raw.img" "$STAGE/unpacked"
for part in system product system_ext vendor odm vendor_dlkm system_dlkm; do
    echo "- Verifying packed $part"
    cmp "$STAGE/$part.img" "$STAGE/unpacked/$part.img" || {
        echo "Packed $part differs from original built image" >&2
        exit 1
    }
    rm "$STAGE/unpacked/$part.img"
done

mv "$STAGE/super.img" "$OUTPUT"
sha256sum "$OUTPUT" > "$OUTPUT.sha256"
cat > "$OUTPUT.txt" <<EOF
DuyKhaiDeX b6q ENGINEERING super preview for SM-F741N
Fold6 F956N: system, product, system_ext
Flip6 F741N: vendor, odm, system_dlkm, vendor_dlkm
Target super max bytes: $SUPER_SIZE
Target group limit bytes: $GROUP_LIMIT
Rebuilt total bytes: $OCCUPIED
NOT FOR FLASH: no AVB resolution, kernel/boot-chain validation or real device boot tests.
EOF
echo "ENGINEERING SUPER PREVIEW BUILT AND RE-UNPACK VERIFIED: $OUTPUT"
echo "No flashable Odin AP was made. DO NOT FLASH THE PREVIEW."
