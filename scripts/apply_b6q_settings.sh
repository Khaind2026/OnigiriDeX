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
    echo "Usage: bash scripts/apply_b6q_settings.sh"
    echo "Replays original Onigiri Settings and no-SIM branding smali patches"
    echo "in the existing, DeX-patched F956N/F741N work tree."
    echo "Does not rebuild, delete, overwrite or flash super.img."
    exit 0
fi
if (( $# != 0 )); then
    echo "Unexpected argument. Use --help." >&2
    exit 2
fi
[[ -f "$WORK_DIR/.b6q-prepared" && -f "$WORK_DIR/.b6q-dex-patched" ]] || {
    echo "No completed b6q DeX port work tree; run bash scripts/port_b6q.sh all" >&2
    exit 1
}
if [[ -f "$WORK_DIR/.b6q-settings-patched" ]]; then
    echo "DuyKhaiDeX Settings patches already completed, no changes made."
    exit 0
fi
if [[ -e "$WORK_DIR/.b6q-settings-attempted" ]]; then
    echo "Previous Settings patch attempt may have partially edited the work tree." >&2
    echo "Review the previous log before retrying. Nothing has been overwritten." >&2
    exit 1
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
STAGE="$(mktemp -d "$OUT_DIR/b6q/.b6q-settings.XXXXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT
mkdir -p "$STAGE/settings/smali"
cp -a "$SETTINGS_SRC/." "$STAGE/settings/smali/"
cat > "$STAGE/settings/module.prop" <<'EOF'
id=duykhaidex_b6q_settings
name=Duy Khải Điều Chỉnh (Flip6)
author=Duy Khải; OnigiriDeX contributors
description=Original Onigiri settings and no-SIM branding patches rebased on F956N
EOF

LOG="$OUT_DIR/b6q/port-logs/Settings-replay-$(date +%Y%m%d-%H%M%S).log"
touch "$WORK_DIR/.b6q-settings-attempted"
echo "- Replaying ORIGINAL OnigiriDeX Settings and no-SIM branding patches"
echo "- Log: $LOG"
if ! "$SRC_DIR/scripts/internal/apply_modules.sh" "$STAGE" 2>&1 | tee "$LOG"; then
    echo "Some original Settings patch hunks did not match Fold6 F956N." >&2
    echo "Partial work tree retained; inspect log rather than repeating firmware steps." >&2
    exit 1
fi

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
