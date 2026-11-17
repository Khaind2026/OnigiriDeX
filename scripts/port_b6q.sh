#!/usr/bin/env bash
# Direct b5q -> b6q port using OnigiriDeX's existing EROFS/module/smali workflow.
# Prepared from the user's verified F956N+F741N images. No Odin flashing.
set -Eeuo pipefail

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export SRC_DIR
export OUT_DIR="$SRC_DIR/out"
export TOOLS_DIR="$OUT_DIR/tools"
export PATH="$TOOLS_DIR/bin:$PATH"
export TARGET_CODENAME=b6q
export TARGET_MODEL=SM-F741N
export SOURCE_FIRMWARE=SM-F956N/SKC
export TARGET_FIRMWARE=SM-F741N/SKC
export TARGET_HAS_SYSTEM_EXT=true
export TARGET_SINGLE_SYSTEM_IMAGE=qssi
export ROM_CODENAME=DuyKhaiDeX
export ROM_VERSION="$(git -C "$SRC_DIR" rev-parse --short HEAD)"
export WORK_DIR="$OUT_DIR/target/b6q/SM-F741N/work_dir"
export APKTOOL_DIR="$OUT_DIR/target/b6q/SM-F741N/apktool"

STAGED="$OUT_DIR/b6q/extracted"
DEVICE_OUTPUT="$OUT_DIR/target/b6q/SM-F741N"
MODE="${1:-all}"
case "$MODE" in
    all|prepare|apply) ;;
    -h|--help)
        cat <<'USAGE'
Usage: bash scripts/port_b6q.sh [all|prepare|apply]
  prepare   Reuse F956N system/product/system_ext and F741N
            vendor/odm/system_dlkm/vendor_dlkm; extract EROFS content
            to an isolated b6q work directory (no phone access).
  apply     Replay the original Flip5 DeX smali patch files using
            scripts/internal/apply_modules.sh on F956N content;
            fail visibly when a Fold5-specific hunk differs.
  all       Run prepare then apply (default).

This is the direct OnigiriDeX ROM port pipeline, NOT an Odin AP builder.
Never flash output under out/target/b6q.
USAGE
        exit 0
        ;;
    *) echo "Unknown mode $MODE (use --help)" >&2; exit 2 ;;
esac

source "$SRC_DIR/scripts/utils/firmware_utils.sh"
source "$SRC_DIR/scripts/utils/module_utils.sh"

prepare()
(
    if [ -e "$WORK_DIR" ] || [ -L "$WORK_DIR" ]; then
        [ -f "$WORK_DIR/.b6q-prepared" ] || {
            echo "Existing work directory has no b6q marker; refusing to overwrite: $WORK_DIR" >&2
            return 1
        }
        echo "Reusing prepared b6q work directory: $WORK_DIR"
        return 0
    fi

    # Verify images once using existing pipeline, not a new independent audit.
    python3 "$SRC_DIR/scripts/verify_b6q_stage.py" >/dev/null || return 1
    command -v extract.erofs >/dev/null || {
        echo "Missing extract.erofs; run 'bash scripts/build_dependencies.sh' first" >&2
        return 1
    }

    mkdir -p "$DEVICE_OUTPUT"
    local stage
    stage="$(mktemp -d "$DEVICE_OUTPUT/.prepare-b6q.XXXXXX")"
    trap 'rm -rf -- "$stage"' EXIT
    mkdir -p "$stage/configs"
    local part model image

    for part in system product system_ext vendor odm system_dlkm vendor_dlkm; do
        case "$part" in
            system|product|system_ext) model=SM-F956N ;;
            *) model=SM-F741N ;;
        esac
        image="$STAGED/$model/$part.img"
        [ -s "$image" ] || { echo "Missing original $model $part image" >&2; return 1; }
        echo "- Extracting $part from $model using existing Onigiri EROFS function"
        EXTRACT_EROFS_PARTITION "$image" "$stage" || return 1
        [ -d "$stage/$part" ] || { echo "Missing extracted $part directory" >&2; return 1; }
        [ -s "$stage/fs_config-$part" ] && [ -s "$stage/file_context-$part" ] || {
            echo "Missing FS/SELinux metadata for $part" >&2; return 1;
        }
        mv "$stage/fs_config-$part" "$stage/configs/fs_config-$part"
        mv "$stage/file_context-$part" "$stage/configs/file_context-$part"
    done

    # The original b5q pipeline keeps system_ext as a real separate partition.
    # Keep its symlinks as supplied by Fold6, rather than injecting b5q paths.
    [ -s "$stage/system/system/etc/floating_feature.xml" ] || {
        echo "Missing F956N floating_feature.xml. Cannot apply DeX module." >&2
        return 1
    }
    [ -s "$stage/system/system/framework/services.jar" ] || {
        echo "Missing F956N services.jar. Cannot replay b5q framework patches." >&2
        return 1
    }

    # Retain a stock AP/BL source manifest; target F741N boot chain is never
    # substituted with F956N bootloader/kernel/DTBO.
    python3 - "$stage" <<'PY'
import json
from pathlib import Path
import sys
dest = Path(sys.argv[1])
(dest / ".b6q-prepared").write_text("F956N system+product+system_ext; F741N vendor+odm+system_dlkm+vendor_dlkm\n")
(dest / "port-origin.json").write_text(json.dumps({
    "status": "STOCK_PORT_TREE_NOT_FLASHABLE",
    "target": "SM-F741N", "donor": "SM-F956N",
    "system": ["system", "product", "system_ext"],
    "hardware": ["vendor", "odm", "system_dlkm", "vendor_dlkm"],
    "original_source": "verified out/b6q/extracted; original Odin packages not modified",
}, indent=2) + "\n")
PY
    [ ! -e "$WORK_DIR" ] || { echo "Work dir created concurrently" >&2; return 1; }
    mv "$stage" "$WORK_DIR"
    echo "DuyKhaiDeX b6q source work directory prepared: $WORK_DIR"
)

apply_port()
(
    [ -f "$WORK_DIR/.b6q-prepared" ] || {
        echo "Prepare the b6q source work directory first." >&2
        return 1
    }
    [ ! -e "$WORK_DIR/.b6q-dex-patched" ] || {
        echo "DeX patch sequence already completed; no reapplication." >&2
        return 0
    }
    [ ! -e "$WORK_DIR/.b6q-dex-attempted" ] || {
        echo "A prior DeX patch attempt already changed the work tree." >&2
        echo "Inspect its failure before continuing. Do not blindly reapply patches." >&2
        return 1
    }
    command -v apktool >/dev/null || {
        echo "Missing apktool: build repository dependencies before applying smali." >&2
        return 1
    }
    mkdir -p "$OUT_DIR/b6q/port-logs"
    local modroot
    modroot="$(mktemp -d "$OUT_DIR/b6q/.b6q-modules.XXXXXX")"
    trap 'rm -rf -- "$modroot"' EXIT

    # Reuse THE SAME Fold5 smali patches. On Samsung F956N a hunk mismatch is
    # an actionable porting error; no unsafe binary offset rewrite is attempted.
    mkdir -p "$modroot/dex"
    cp -a "$SRC_DIR/target/b6q/patches/dex/." "$modroot/dex/"
    cp -a "$SRC_DIR/target/b5q/patches/dex/smali" "$modroot/dex/smali"
    local log="$OUT_DIR/b6q/port-logs/DeX-replay-$(date +%Y%m%d-%H%M%S).log"
    touch "$WORK_DIR/.b6q-dex-attempted"
    echo "- Replaying actual OnigiriDeX b5q DeX smali patches on F956N"
    echo "- Log: $log"
    if ! "$SRC_DIR/scripts/internal/apply_modules.sh" "$modroot" 2>&1 | tee "$log"; then
        echo "b5q patch does not apply as-is to Fold6. See $log" >&2
        echo "The b6q work directory is retained for updating/rebasing this patch." >&2
        return 1
    fi
    "$SRC_DIR/scripts/prepare_signing_keys.sh"
    # Same APK build path as b5q make_rom.sh, but serialize builds for clear errors.
    if [ -d "$APKTOOL_DIR" ]; then
        while IFS= read -r app; do
            local relative partition path
            relative="${app#"$APKTOOL_DIR"/}"
            partition="${relative%%/*}"
            path="${relative#*/}"
            if [ "$partition" = system ]; then
                "$SRC_DIR/scripts/apktool.sh" b system "system/$path" || return 1
            else
                "$SRC_DIR/scripts/apktool.sh" b "$partition" "$path" || return 1
            fi
        done < <(find "$APKTOOL_DIR" -type d \( -name '*.apk' -o -name '*.jar' \) | sort)
    fi
    touch "$WORK_DIR/.b6q-dex-patched"
    echo "DeX source patch replay complete in $WORK_DIR (NOT boot-tested; no Odin AP)."
}

case "$MODE" in
    prepare) prepare ;;
    apply) apply_port ;;
    all) prepare && apply_port ;;
esac
