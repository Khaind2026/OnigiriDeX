# DuyKhaiDeX Flip6 device configuration, adapted from target/b5q/config.sh.
# Port source: Galaxy Z Fold6 SM-F956N SKC One UI 7 / Android 15.
# Boot chain, kernel, vendor and dynamic group belong to Flip6 SM-F741N.
# A port work tree is not a bootable or flashable image.
TARGET_NAME="Galaxy Z Flip6"
TARGET_CODENAME="b6q"
TARGET_MODEL="SM-F741N"
TARGET_API_LEVEL=35
TARGET_PRODUCT_FIRST_API_LEVEL=34
TARGET_VENDOR_API_LEVEL=34
TARGET_SINGLE_SYSTEM_IMAGE="qssi"
TARGET_HAS_SYSTEM_EXT=true
TARGET_KEEP_ORIGINAL_SIGN=true
TARGET_INCLUDE_PATCHED_VBMETA=false
TARGET_DISABLE_AVB_SIGNING=false
TARGET_FIRMWARE="SM-F741N/SKC"
SOURCE_FIRMWARE="SM-F956N/SKC"
ROM_CODENAME="DuyKhaiDeX"

# Do not duplicate b5q (Snapdragon 8 Gen 2) HFR, SSRM, camera, cover
# resolution, EGL, or power tuning values. Preserve b6q firmware settings
# and port only required DeX behavior. F956N q6q framework patches must
# be checked against their own APK/JAR revisions before any flash output.
