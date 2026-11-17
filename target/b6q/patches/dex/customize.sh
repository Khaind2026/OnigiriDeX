# DuyKhaiDeX Flip6: reuses OnigiriDeX's module engine and DeX configuration.
# This is sourced by scripts/internal/apply_modules.sh with WORK_DIR set to b6q.
# The Fold5-only native SurfaceFlinger offsets and vendor SELinux rules MUST
# NOT be copied onto F956N / F741N without rebasing against real binaries.
[ "${TARGET_CODENAME:-}" = b6q ] || ABORT "This DeX module only supports b6q"
[ "${TARGET_MODEL:-}" = SM-F741N ] || ABORT "Only Korean Flip6 SM-F741N is configured"

for FILE in \
    system/priv-app/KnoxDesktopLauncher/KnoxDesktopLauncher.apk \
    system/priv-app/DesktopModeUiService/DesktopModeUiService.apk \
    system/priv-app/DesktopSystemUI/DesktopSystemUI.apk \
    system/etc/permissions/privapp-permissions-com.sec.android.app.desktoplauncher.xml \
    system/etc/permissions/privapp-permissions-com.sec.android.desktopmode.uiservice.xml \
    system/etc/permissions/privapp-permissions-com.sec.android.dexsystemui.xml; do
    [ -s "$WORK_DIR/system/$FILE" ] || ABORT "Missing Fold6 DeX source component: $FILE"
done

SET_FLOATING_FEATURE_CONFIG "SEC_FLOATING_FEATURE_COMMON_CONFIG_DEX_MODE" "dual,wireless" || ABORT "Cannot set DeX mode"
SET_FLOATING_FEATURE_CONFIG "SEC_FLOATING_FEATURE_COMMON_SUPPORT_KNOX_DESKTOP" "TRUE" || ABORT "Cannot enable native Knox desktop flag"

# DuyKhaiDeX branding (Samsung Settings patch must be separately ported to
# F956N resources; these properties do not rename APK resources).
SET_PROP system ro.onigiri.codename DuyKhaiDeX || ABORT "Unable to set ROM codename"
SET_PROP system ro.duykhaidex.device b6q || ABORT "Unable to set ROM device"
