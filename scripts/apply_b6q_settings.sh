#!/usr/bin/env bash
# Replay the existing OnigiriDeX settings/branding smali patches on the
# already prepared F956N+F741N b6q work tree. Does not unpack firmware again.
# No boot, Odin AP, or flashing.
set -Eeuo pipefail

SRC_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
export SRC_DIR OUT_DIR="$SRC_DIR/out" TOOLS_DIR="$SRC_DIR/out/tools"
export PATH="$TOOLS_DIR/bin:$PATH"
source "$SRC_DIR/target/b6q/config.sh"
export TARGET_CODENAME TARGET_MODEL TARGET_HAS_SYSTEM_EXT TARGET_SINGLE_SYSTEM_IMAGE ROM_CODENAME
export ROM_VERSION="$(git -C "$SRC_DIR" rev-parse --short HEAD)"
export WORK_DIR="$OUT_DIR/target/b6q/SM-F741N/work_dir"
export APKTOOL_DIR="$OUT_DIR/target/b6q/SM-F741N/apktool"

if [[ "${1:-}" == "--help" ]]; then
    echo "Usage: bash scripts/apply_b6q_settings.sh [--resume]"
    echo "Replays original Onigiri Settings and no-SIM branding smali patches"
    echo "in the existing, DeX-patched F956N/F741N work tree."
    echo "Use --resume only after a failed patch attempt; successful patches are checkpointed."
    echo "Does not rebuild, delete, overwrite or flash super.img."
    exit 0
fi
if (( $# > 1 )) || [[ $# == 1 && "$1" != --resume ]]; then
    echo "Unexpected argument. Use --help or --resume." >&2
    exit 2
fi
MODE="${1:-normal}"
[[ -f "$WORK_DIR/.b6q-prepared" && -f "$WORK_DIR/.b6q-dex-patched" ]] || {
    echo "No completed b6q DeX port work tree; run bash scripts/port_b6q.sh all" >&2
    exit 1
}
if [[ -f "$WORK_DIR/.b6q-settings-patched" ]]; then
    echo "DuyKhaiDeX Settings patches already completed, no changes made."
    exit 0
fi
LEDGER="$WORK_DIR/.b6q-settings-patch-progress"
if [[ -e "$WORK_DIR/.b6q-settings-attempted" ]]; then
    if [[ "$MODE" != --resume ]]; then
        echo "Previous Settings attempt exists. Use --resume to continue safely." >&2
        exit 1
    fi
    if [[ ! -e "$LEDGER" ]]; then
        # The screenshot shows the very FIRST original patch failed atomically
        # because F956N has no values-en-rCA/strings.xml. No Settings hunk was
        # applied by git (it was a single failed git apply transaction).
        LAST_LOG="$(find "$OUT_DIR/b6q/port-logs" -maxdepth 1 -name 'Settings-replay-*.log' -type f -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
        [[ -f "$LAST_LOG" ]] || { echo "Cannot locate previous Settings log" >&2; exit 1; }
        if ! grep -Fq 'res/values-en-rCA/strings.xml' "$LAST_LOG" ||
           ! grep -Fq 'No such file or directory' "$LAST_LOG" ||
           [[ "$(grep -c '^- Applying ' "$LAST_LOG")" != 1 ]]; then
            echo "Prior patch state cannot be verified as atomic first-patch failure." >&2
            echo "Preserving work tree; examine $LAST_LOG" >&2
            exit 1
        fi
        echo "- Verified previous attempt failed on its first patch; safe to resume."
    fi
fi
for tool in apktool git zipalign; do
    command -v "$tool" >/dev/null || { echo "Missing required tool $tool" >&2; exit 1; }
done

# Preserve the upstream patch chain, rather than doing text replacement on
# compiled APKs. Do not import the Fold5 vendor SELinux/car standby customize.
# The existing source branch already brands the menu as 'Duy Khải Điều Chỉnh'
# and the no-SIM carrier text as 'Duy Khải DeX 0862134811'.
SETTINGS_SRC="$SRC_DIR/onigiri/mods/settings/smali"
[[ -d "$SETTINGS_SRC/system/priv-app/SecSettings/SecSettings.apk" ]] || {
    echo "Missing upstream SecSettings patch series" >&2
    exit 1
}
[[ -d "$SETTINGS_SRC/system_ext/priv-app/SystemUI/SystemUI.apk" ]] || {
    echo "Missing upstream no-SIM branding patch" >&2
    exit 1
}
mkdir -p "$OUT_DIR/b6q/port-logs"
# Exact original OnigiriDeX source patches; adapt only omitted optional
# locale strings from a TEMPORARY copy. APK/JAR smali and resource IDs retain
# full git-apply semantics, so incompatible Fold6 code still fails visibly.
source "$SRC_DIR/scripts/utils/module_utils.sh"
STAGE="$(mktemp -d "$OUT_DIR/b6q/.b6q-settings.XXXXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT
LOG="$OUT_DIR/b6q/port-logs/Settings-replay-$(date +%Y%m%d-%H%M%S).log"
touch "$WORK_DIR/.b6q-settings-attempted" "$LEDGER"
echo "- Replaying original Settings patches, preserving existing DeX work tree"
echo "- Missing optional Fold5 locale XML hunks will be filtered on the fly"
echo "- Progress ledger: $LEDGER"
echo "- Log: $LOG"

apply_one_target()
{
    local target="$1" partition relative decoded original name key staged_patch
    partition="${target%%/*}"
    if [[ "$partition" = system ]]; then
        relative="$target"
        decoded="$APKTOOL_DIR/system/${target#system/}"
    else
        relative="${target#"$partition"/}"
        decoded="$APKTOOL_DIR/$target"
    fi
    DECODE_APK "$partition" "$relative" || return 1
    for original in "$SETTINGS_SRC/$target"/*.patch; do
        [[ -f "$original" ]] || continue
        name="${original#"$SETTINGS_SRC"/}"
        key="$name|$(sha256sum "$original" | awk '{print $1}')"
        if grep -Fxq -- "$key" "$LEDGER"; then
            echo "- Already patched: $name"
            continue
        fi
        if grep -Fq -- "$name|" "$LEDGER"; then
            echo "Patch changed since earlier application: $name" >&2
            return 1
        fi
        staged_patch="$STAGE/$(basename "$original")"
        cp "$original" "$staged_patch"
        python3 "$SRC_DIR/scripts/adapt_b6q_settings_patches.py" \
            --patch "$staged_patch" --decoded "$decoded" || return 1
        if ! APPLY_PATCH "$partition" "$relative" "$staged_patch" 2>&1 | tee -a "$LOG"; then
            echo "Patch failed: $name" >&2
            echo "Previously successful patches are recorded and will be skipped on --resume." >&2
            return 1
        fi
        printf '%s\n' "$key" >> "$LEDGER"
    done
}

# Same source patch set as Onigiri. Start with previously failed SystemUI
# patch to solve the observed F956N resource difference first.
FIRST="system_ext/priv-app/SystemUI/SystemUI.apk"
{
    printf '%s\n' "$FIRST"
    find "$SETTINGS_SRC" -type d \( -name '*.apk' -o -name '*.jar' \) |
        sed "s|^$SETTINGS_SRC/||" | grep -Fxv "$FIRST" | LC_ALL=C sort
} | while IFS= read -r target; do
    apply_one_target "$target" || exit 1
done

"$SRC_DIR/scripts/prepare_signing_keys.sh"
# Rebuild the decoded APKs/JARs using the original OnigiriDeX apktool helper.
# Existing DeX-decoded packages are permitted: they're already patched.
if [[ -d "$APKTOOL_DIR" ]]; then
    while IFS= read -r app; do
        relative="${app#"$APKTOOL_DIR"/}"
        partition="${relative%%/*}"
        path="${relative#*/}"
        if [[ "$partition" == "system" ]]; then
            "$SRC_DIR/scripts/apktool.sh" b system "system/$path"
        else
            "$SRC_DIR/scripts/apktool.sh" b "$partition" "$path"
        fi
    done < <(find "$APKTOOL_DIR" -type d \( -name '*.apk' -o -name '*.jar' \) | sort)
fi
touch "$WORK_DIR/.b6q-settings-patched"
echo "DuyKhaiDeX b6q Settings/brand patch replay completed (not boot-tested)."
echo "Existing super preview was NOT modified. Rebuild a NEW preview after reviewing patches."
