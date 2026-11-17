# DuyKhaiDeX — SM-F741N / Z Flip6 Android 15 (One UI 7), Fold6 donor port

**Status:** Korean F741N/F956N firmware selection and DuyKhaiDeX display branding updated in source. **Not built or tested on device.** This is an experimental **Fold6-to-Flip6 system port**, preserving the Flip6 boot chain and hardware-specific firmware. Maintain on branch `dk-f741n-oneui7-port`; do not copy b5q binaries or merge into Flip5 release pipeline.

## Why Fold6 donor

The existing OnigiriDeX Z Flip5 build uses:
- **System-side donor: SM-F946B (Z Fold5, q5q)** — `system`, `product`, and `system_ext` from `scripts/internal/create_work_dir.sh`.
- **Hardware target: SM-F731B/N (Z Flip5, b5q)** — `vendor`, `odm`, `vendor_dlkm`, `odm_dlkm`, `system_dlkm`, `boot`, `vendor_boot`, `dtbo`, `recovery`, and `vbmeta` from target or its matching rebuilt kernel.
- Device-specific patches adapt settings, external/cover displays and DeX.

For this experimental build, **use SM-F956N (Z Fold6, q6q) Android 15 / One UI 7 as donor** and **SM-F741N (Z Flip6, b6q) Android 15 / One UI 7 as hardware target**. Both are Snapdragon 8 Gen 3 devices, but a shared SoC does **not** guarantee framework/vendor compatibility.

**Not** a direct replacement of `F946B` with `F956N` in `firmware.json`: current scripts have hard-coded b5q assumptions.

## 1. Confirm actual firmware and phone

- Read F741N model, Android/One UI, incremental build, CSC and **bootloader binary** from the actual phone; avoid binary downgrade or mixing base revisions.
- Select a full official **SM-F741N** Android 15 image for the hardware target and an **SM-F956N** Android 15 / One UI 7 image for the donor. Do not pick mismatched Android major versions.
- Selected Odin AP names, visible in the user's folder: **Flip6 `F741NKSS2BYGB`** and **Fold6 `F956NKSS2BYGB`** (Korean SKC package family). CP filenames appear to contain `F741NKSU2BYCG` and `F956NKSU2BYCG`; CSC names `F741NOKR2BYGB` and `F956NOKR2BYGB`. Confirm exact full names before extraction. Matching suffixes do NOT prove vendor/framework compatibility.
- Verify the complete Odin AP/BL/CP/CSC packages. Store matching original firmware and an independent backup.
- Avoid flashing stock donor Fold6 AP, bootloader, modem, `vendor`, `dtbo`, `vbmeta`, or kernel to a Flip6.

## 2. Non-destructive firmware inventory

- Inspect F741N and F956N AP and BL metadata and their `system`, `product`, `system_ext`, `vendor`, `odm`, `vendor_dlkm`, `system_dlkm`, `boot`, `init_boot`, `vendor_boot`, `dtbo`, `recovery`, `vbmeta` images.
- Extract target `super` metadata with `lpdump`: actual partition list, slot/virtual A/B layout, total/group sizes and filesystem types. Never reuse the b5q fixed sizes or assume a matching partition layout.
- Compare Fold6 system services/framework, permissions, feature flags, VINTF matrix, shipping API and security patch, plus proprietary feature dependencies, against Flip6 vendor.
- Record SELinux labels, `fs_config` and framework dependencies before any integration.

## 3. New device-specific build path

- Add `target/b6q/config.sh` only after reading real F741N firmware properties; add a model-specific donor mapping `SM-F741N -> SM-F956N` in the firmware configuration.
- Refactor `buildenv.sh`, `gen_config_file.sh`, `create_work_dir.sh`, `make_rom.sh`, `build_odin.sh`, and validation/release scripts so b5q and b6q have independent config/work/output directories. Do not loosen the original b5q assertion without adding equivalent b6q checks.
- Extend the donor/target composition pattern: Fold6 `system`/`product`/`system_ext`, Flip6 `vendor`/`odm`/`*_dlkm` and hardware-specific partitions.
- Start with a minimal hybrid build (no unrelated Fold5 patches), prove partition compatibility and image integrity, then port modifications incrementally.

## 4. Kernel

- For the first experiment keep the **exact F741N kernel/boot images, device trees and modules** from the matching target firmware (where the build allows an unchanged validated image).
- Later acquire build-matched Samsung SM-F741N kernel sources, toolchain and defconfig; verify module/kernel ABI and compile independently if needed.
- Existing `external/kernel` and `out/target/b5q/kernel` are Snapdragon 8 Gen 2/SM8550 Z Flip5, **not** suitable for the 8 Gen 3/SM8650 Flip6. No renamed cross-flashing.
- KernelSU/susFS is a separate optional milestone once the base system is stable.

## 5. Port DK features carefully

- First port branding `DuyKhaiDeX` and other cosmetic changes by checking exact APK resource IDs and methods in the Fold6 One UI 7 framework.
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

## Verified source branding in the Flip6 development branch

- Proposed public ROM name: **DuyKhaiDeX** (ROM_CODENAME changed in this branch).
- Samsung Settings menu string and category: **Duy Khải Điều Chỉnh**.
- No-SIM carrier-text patch: **DuyKhaiDeX 0862134811**.
- Keep original source copyrights, acknowledgments and upstream license/NOTICE intact.
- The patched APK/JAR assets are still based on Fold5 and must be rebased and validated against F956N One UI 7 before they can be shipped on b6q.

## First step on user's Debian WSL2

The Windows screenshot shows both models' Odin packages together in:

```text
D:\\mod fold 6\\SAMFW.COM_SM-F741N_SKC_F741NKSS2BYGB_fac
```

The new preflight tool filters by exact model and accepts the **same directory** as both inputs:

```bash
cd ~/OnigiriDeX
git fetch origin
git switch dk-f741n-oneui7-port
git pull --ff-only

FW_DIR='/mnt/d/mod fold 6/SAMFW.COM_SM-F741N_SKC_F741NKSS2BYGB_fac'
python3 scripts/preflight_f741n.py --flip6 "$FW_DIR" --fold6 "$FW_DIR"
```

`inventory_passed_not_buildable` means only that the four Odin archive names for both models match the expected identifiers; it does **not** verify their contents.

Once the inventory passes, optionally **verify Odin MD5 checksums and import both models separately as symlinks**, without re-copying the 30 GB of source files:

```bash
python3 scripts/import_duykhaidex_f741n.py --folder "$FW_DIR"
```

This reads all Odin archives for MD5 integrity (may be I/O intensive) and writes `out/odin/SM-F741N_SKC/` and `out/odin/SM-F956N_SKC/` symlinks plus import metadata. Keep the source firmware folder on drive D unchanged and mounted. The importer refuses to overwrite existing imports. **It does not extract partition images, build an AP or make a ROM bootable.** Tests without device data:

```bash
python3 -m unittest discover -s tests -p 'test_f741n_preflight.py' -v
```

Before any experimental packaging, inspect actual phone model, PDA, CSC and bootloader revision (`adb shell getprop ro.bootloader` and `adb shell getprop ro.product.model`). Then independently verify Odin trailing MD5, extract firmware partitions in **separate** work directories, dump target super partition metadata, assess VINTF/SELinux compatibility and implement a b6q-specific build graph. The existing b5q `make_rom` and `build_odin` scripts are not safe to use for F741N.

Do not flash AP/BL/CP/CSC from Fold6 onto Flip6. No downloadable Flip6 ROM has been generated or device-tested by this source change.


## Phase 2: stock Odin AP/BL header inventory (read-only)

After BOTH Korean firmware imports report
`F741N/F956N Odin imports verified. No ROM built or flashed.`, use:

```bash
cd ~/OnigiriDeX
git pull --ff-only
python3 scripts/inspect_f741n_f956n_archives.py
```

The script lists archive headers, checks whether AP contains `super.img.lz4` or
individual partition images, and records the names of boot-related images.
It generates `out/reports/f741n-f956n-odin-layout.json` and prints a short
summary without extracting images or modifying any firmware file. Bring back
the printed summary before writing an extractor for the actual partition
layout. It is not an Android ROM build.

The imported archives can be large but TAR header enumeration skips payload
bytes. Read-only archive scanning does NOT establish DeX support, match
framework APIs, prove boot compatibility, or validate F741N bootloader binary
on the physical phone. Keep Flip6 low-level binaries separate from Fold6.


## Phase 3: bounded super metadata inspection (no 12 GB extraction)

Both Korean Odin AP archives have `super.img.lz4` (as confirmed by the
user's `inspect_f741n_f956n_archives.py` terminal output; 12 AP TAR
members and 33 BL TAR members each). Use the new read-only metadata parser:

```bash
cd ~/OnigiriDeX
git pull --ff-only
command -v lz4 || sudo apt install lz4
python3 scripts/inspect_super_f741n_f956n.py
```

The script reads at most the first 4 MiB of *decompressed logical image data*
from each verified AP, decoding Android sparse chunks as needed. It validates
LP geometry, header and tables SHA-256 and lists groups, partitions and their
size in bytes. It does not write a full `super.img`, unpack any partition or
modify the firmware. Results go to
`out/reports/f741n-f956n-super-metadata.json`.

**Important:** if a specific Samsung firmware uses an unsupported LP layout,
the script fails with an error instead of assuming a standard b5q partition
geometry. In that case capture the error; do not force the Flip5 geometry.
After a successful report, compare the target partition/group limits with
the donor, inspect their Android/VINTF/SELinux dependencies and then implement
a b6q-specific build before producing any Odin AP.

### liblp header parser correction (2026-11-18)

If the old scanner reported `Unexpected LP primary metadata header (slot 0)`,
it rejected AOSP's standard `LpMetadataHeader.major_version=10` as though
it were 1 or 2. Android defines major **10**, minor **0..2**; the previous
condition confused the major version with the minor version. This was
corrected in `scripts/inspect_super_f741n_f956n.py`. The geometry and header
layout remain unchanged and neither Odin archives nor device firmware need
re-importing. Retry with:

```bash
cd ~/OnigiriDeX
git pull --ff-only
python3 scripts/inspect_super_f741n_f956n.py
```

If a different error is reported after this correction, preserve the exact
terminal text; don't attempt a ROM flash or override structural assertions.
