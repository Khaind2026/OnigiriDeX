# DK điều chỉnh — SM-F741N / Z Flip6 Android 15 (One UI 7), Fold6 donor port

**Status:** research and planning. **Not built or tested.** This is an experimental **Fold6-to-Flip6 system port**, preserving the Flip6 boot chain and hardware-specific firmware. Maintain on branch `dk-f741n-oneui7-port`; do not copy b5q binaries or merge into Flip5 release pipeline.

## Why Fold6 donor

The existing OnigiriDeX Z Flip5 build uses:
- **System-side donor: SM-F946B (Z Fold5, q5q)** — `system`, `product`, and `system_ext` from `scripts/internal/create_work_dir.sh`.
- **Hardware target: SM-F731B/N (Z Flip5, b5q)** — `vendor`, `odm`, `vendor_dlkm`, `odm_dlkm`, `system_dlkm`, `boot`, `vendor_boot`, `dtbo`, `recovery`, and `vbmeta` from target or its matching rebuilt kernel.
- Device-specific patches adapt settings, external/cover displays and DeX.

For a matching new-generation device pair, **propose SM-F956B (Z Fold6, q6q) Android 15 / One UI 7 as donor** and **SM-F741N (Z Flip6, b6q) Android 15 / One UI 7 as hardware target**. Both are Snapdragon 8 Gen 3 devices, but a shared SoC does **not** guarantee framework/vendor compatibility.

**Not** a direct replacement of `F946B` with `F956B` in `firmware.json`: current scripts have hard-coded b5q assumptions.

## 1. Confirm actual firmware and phone

- Read F741N model, Android/One UI, incremental build, CSC and **bootloader binary** from the actual phone; avoid binary downgrade or mixing base revisions.
- Select a full official **SM-F741N** Android 15 image for the hardware target and an **SM-F956B** Android 15 / One UI 7 image for the donor. Do not pick mismatched Android major versions.
- Example Fold6 Android 15 donor candidate: `F956BXXU2BYD9` (candidate, not yet selected or pinned); exact donor build, CSC, patch level and compatibility must be verified against the target.
- Verify the complete Odin AP/BL/CP/CSC packages. Store matching original firmware and an independent backup.
- Avoid flashing stock donor Fold6 AP, bootloader, modem, `vendor`, `dtbo`, `vbmeta`, or kernel to a Flip6.

## 2. Non-destructive firmware inventory

- Inspect F741N and F956B AP and BL metadata and their `system`, `product`, `system_ext`, `vendor`, `odm`, `vendor_dlkm`, `system_dlkm`, `boot`, `init_boot`, `vendor_boot`, `dtbo`, `recovery`, `vbmeta` images.
- Extract target `super` metadata with `lpdump`: actual partition list, slot/virtual A/B layout, total/group sizes and filesystem types. Never reuse the b5q fixed sizes or assume a matching partition layout.
- Compare Fold6 system services/framework, permissions, feature flags, VINTF matrix, shipping API and security patch, plus proprietary feature dependencies, against Flip6 vendor.
- Record SELinux labels, `fs_config` and framework dependencies before any integration.

## 3. New device-specific build path

- Add `target/b6q/config.sh` only after reading real F741N firmware properties; add a model-specific donor mapping `SM-F741N -> SM-F956B` in the firmware configuration.
- Refactor `buildenv.sh`, `gen_config_file.sh`, `create_work_dir.sh`, `make_rom.sh`, `build_odin.sh`, and validation/release scripts so b5q and b6q have independent config/work/output directories. Do not loosen the original b5q assertion without adding equivalent b6q checks.
- Extend the donor/target composition pattern: Fold6 `system`/`product`/`system_ext`, Flip6 `vendor`/`odm`/`*_dlkm` and hardware-specific partitions.
- Start with a minimal hybrid build (no unrelated Fold5 patches), prove partition compatibility and image integrity, then port modifications incrementally.

## 4. Kernel

- For the first experiment keep the **exact F741N kernel/boot images, device trees and modules** from the matching target firmware (where the build allows an unchanged validated image).
- Later acquire build-matched Samsung SM-F741N kernel sources, toolchain and defconfig; verify module/kernel ABI and compile independently if needed.
- Existing `external/kernel` and `out/target/b5q/kernel` are Snapdragon 8 Gen 2/SM8550 Z Flip5, **not** suitable for the 8 Gen 3/SM8650 Flip6. No renamed cross-flashing.
- KernelSU/susFS is a separate optional milestone once the base system is stable.

## 5. Port DK features carefully

- First port branding `DK điều chỉnh` and other cosmetic changes by checking exact APK resource IDs and methods in the Fold6 One UI 7 framework.
- Port cover-screen behavior, DeX, USB external display and refresh-rate changes as **separate** patches. Require functional and stability tests; there is no guaranteed 120 Hz DeX or mirror unlock.
- Validate phone-specific components including camera, radio, Wi-Fi, fingerprint, thermals, fold-state, display IC/panel behavior, and proprietary services.
- The Eureka module in current OnigiriDeX requires additional S24 adaptive-display files; keep it optional during early compatibility testing.

## 6. Validation and release gates

1. Confirm model and bootloader revision before any install test; retain original firmware and backups.
2. Validate patch integrity, APK/JAR rebuild, SELinux and VINTF.
3. Check target partition sizes, AVB flags, boot chain, boot/recovery image headers and Odin package contents.
4. Create an **SM-F741N-only Odin AP** once partition images pass verification. Do not reuse or flash a Fold6/Flip5 AP.
5. Test boot, recovery, touch, fold-state, both displays, charging, connectivity, thermal behavior, DeX/external monitor and fallback firmware.
6. Never call it a completed ROM until a successful build and model-matched validation exist.

## First step on user's Debian WSL2

Run these **read-only** checks to locate firmware:

```bash
cd ~/OnigiriDeX
git status --short
find /mnt/d -maxdepth 5 -type f \( -iname 'AP_F741N*.tar.md5' -o -iname 'AP_F956B*.tar.md5' -o -iname '*F741N*.zip' -o -iname '*F956B*.zip' \) -print 2>/dev/null
```

Confirm target bootloader binary and exact F741N/F956B Android 15 software versions before changing build code.

