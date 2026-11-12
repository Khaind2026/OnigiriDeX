# DK điều chỉnh — SM-F741N (b6q), Android 15 / One UI 7: port plan

**Status:** planning only. The current ROM build supports SM-F731B / SM-F731N (`b5q`). No F741N AP has been built, validated, or flashed. Keep this work on `dk-f741n-oneui7-port`; do not change the Flip5 release pipeline until the F741N build has independent tests.

## 0. Confirm device and baseline

- Read the *current* SM-F741N build, bootloader revision, CSC, Android version, kernel release and bootloader lock state (Android Settings/Download Mode, or read-only `adb shell getprop`/`uname -r`).
- Pick an official **SM-F741N** Android 15 / One UI 7 full firmware set with a compatible bootloader revision. Example reference: F741NKSU2BYCJ / F741NOKR2BYCJ (KOO, bootloader binary 2). This is not a safe target for a phone already on a higher bootloader binary.
- Retain verified originals of AP, BL, CP, CSC and an independent user-data backup. No files from a different model are suitable for the boot chain, modem or device-specific partitions.
- Collect original Odin package checksums; never flash an unverified package.

## 1. Inspect firmware, no flash

- Work with the existing Debian 13/WSL2 toolchain, and reserve disk space.
- Inspect AP and BL archive member names, partition images, `lpdump` output for `super`, filesystem types, partition list and group size, target build properties, VINTF compatibility, and original `boot`, `init_boot`, `vendor_boot`, `dtbo`, `vbmeta`, `vendor_dlkm`, `system_dlkm`, recovery.
- Record the actual b6q partition map and metadata. Never reuse the b5q hard-coded super partition sizes or assumptions.

## 2. Device-specific branch

- Create `target/b6q/config.sh` based on **measured F741N properties**, not copied b5q guesses.
- Extend `onigiri/configs/firmware.json` and `buildenv.sh` to select SM-F741N and new b6q paths without affecting SM-F731B/N.
- Generalize `scripts/internal/gen_config_file.sh`, `scripts/make_rom.sh`, `scripts/build_odin.sh`, and release/test logic to separate b5q and b6q output directories and constraints. Use real F741N partition metadata.
- Start with a **stock-F741N-based experimental build** (no Fold5 donor, no b5q-only patches), then add compatible changes incrementally.

## 3. Kernel: first preserve stock

- First milestone: preserve the original **F741N** kernel, device trees and modules from the matching stock AP, and validate hashes/boot layout. This reduces variables.
- Only after baseline verification, obtain model/build-matched Samsung kernel source from Samsung Open Source Release Center (or an independently verified mirror), inspect its `build.sh` and matching toolchain, compile/test independently.
- Never reuse `external/kernel` (currently SM8550/Flip5) or `out/target/b5q/kernel` as b6q images. The current 5.15 build/kernel packaging asserts b5q and cannot be repurposed by renaming.
- Put b6q kernel changes in a separate source pin/patch directory with reproducible checksums; KernelSU/susFS is a separate later milestone.

## 4. Android 15 / One UI 7 patches

- Begin with cosmetics (DK điều chỉnh) and settings changes only after validating APK/JAR versions.
- Port patches only when their exact target smali methods, resource IDs, SELinux contexts, overlays and required files exist in the F741N base.
- DeX output, cover display, HDMI mirror/120 Hz, camera and thermal patches are independent experimental features requiring instrumented tests. Do not assume b5q patches apply unchanged.
- Keep Eureka optional: the current module requires additional verified S24 adaptive display assets.

## 5. Build gates before any device flash

1. Static tests: script syntax, configuration checks, patch integrity, APK/JAR recompilation.
2. Validate image contents, filesystem metadata, SELinux labels, partition sizes, AVB/boot chain compatibility and exact target model.
3. Produce an F741N-specific Odin AP in a separate output directory; validate tar member names, image checksums and a round-trip `super` unpack.
4. Retain full matching original firmware and a device recovery plan. Flash only after the owner explicitly approves and confirms device model/bootloader compatibility.
5. Check first boot, touch and folded-panel behavior, radio, cameras, Wi-Fi, thermals, USB, external display, DeX, and OTA separately.

## Immediate non-destructive checks in WSL

```bash
cd ~/OnigiriDeX
git status --short
git branch --show-current
ls /mnt/d
```

If USB debugging is enabled and the phone is connected:

```bash
adb devices
adb shell getprop ro.product.vendor.model
adb shell getprop ro.build.version.incremental
adb shell getprop ro.boot.bootloader
adb shell getprop ro.build.version.release
adb shell uname -r
```

If adb is not available or the phone cannot connect, provide screenshots of Settings > About phone > Software information and Download Mode's bootloader information instead.

**Stop conditions:** firmware version does not match the requested model/Android; binary downgrade; missing device-specific partitions; new binary image cannot be verified; build scripts still assert b5q.
