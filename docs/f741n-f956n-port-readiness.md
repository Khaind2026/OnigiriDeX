# DuyKhaiDeX Flip6 F741N / Fold6 F956N — evidence and next engineering gates

> **Research status: NOT BOOT-VERIFIED, NOT FLASHABLE.**
> This note records evidence from the local diagnostic archive generated on
> 2026-11-18; it does not include firmware images or private device data.
>
> Target: SM-F741N / F741NKSS2BYGB (b6q). Donor framework:
> SM-F956N / F956NKSS2BYGB (q6q). Both on One UI 7 / Android 15.

## Verified on Debian host

| Area | Evidence | Remaining proof |
|---|---|---|
| Source selection | F956N: system, product, system_ext. F741N: vendor, odm, system_dlkm, vendor_dlkm | Actual hardware service compatibility |
| EROFS stage | 7 filesystem images have matching manifest sizes and recognized EROFS signatures | Full SELinux, symlink, shared library / HAL semantics |
| Boot source | 7 stock F741N boot-related AP images match recorded SHA256 checksums | First-stage fstab, boot ramdisks, kernel ABI, rollback |
| System super | Branded super engineering preview exists; builder checked round-trip lpunpack against its rebuilt partition images | Modified image AVB/verity trust and actual boot |
| DeX patch | Prepared and patched tree markers present; DeX replay log exists | APK/JAR runtime behavior, DexService, external display Hz and screen-state tests |

## Important AVB incompatibility to resolve

The **stock F741N BL top-level vbmeta.img** (AVB0; SHA256_RSA4096)
contains *direct* hashtree descriptors for system, product, system_ext,
vendor, odm, system_dlkm, and vendor_dlkm, plus hash descriptors for
boot/init_boot/recovery/vendor_boot. The *chain* descriptor targets are
**dtbo, optics, prism** (NOT vbmeta_system).

The stock F741N AP **vbmeta_system.img** also lists hashtree descriptors
for the seven dynamic partitions. Its existence alone does not establish
how it is accepted in the device's full boot trust chain.

The b6q super preview builder explicitly builds EROFS images with
`--no-avb`; these images cannot be assumed to match stock root digests.
Do not re-use a stock signature and claim validation. Do not flash the
engineering preview.

**Next engineering gate:** compare actual rebuilt-image structure and
verity metadata to the target's trust policy, inspect stock boot images and
first-stage fstab, and establish an independently reviewed
device-recoverable validation strategy. Parsing AVB0 metadata does **not**
verify a signature.

## VINTF and HAL progress

- Donor F956N framework contains **six** compatibility matrices:
  levels 5, 6, 7, 8, 202404, and `compatibility_matrix.device.xml`.
- Donor matrix entries were all **optional at the HAL-name level** in
  the existing simplified report. This does not imply interface/version
  compatibility and does not imply zero errors.
- Target F741N vendor/odm manifest lists **132 distinct HAL names**.
- Target F741N vendor device compatibility matrix lists **five required HAL
  names**: `android.frameworks.sensorservice`, `android.hidl.allocator`,
  `android.hidl.manager`, `android.hidl.memory`, `android.hidl.token`.
  All five also appear among the **27 HAL names** declared in donor
  F956N system/system_ext/product framework manifests.
- This is a **5/5 name-level match**, *not* a libvintf/FCM runtime pass.
  It does not check HAL transport, version, interface instance, optional
  combinations, device SKU, active APEX manifests or kernel config.
- The user's Debian environment did **not** report a `checkvintf`
  executable in the uploaded diagnostic ZIP.

### Changes now implemented in GitHub

1. `scripts/audit_b6q_vintf_mounts.py` now audits **both** directions:
   framework matrix → vendor manifest *and* device matrix → framework
   manifests. Missing/unavailable data is not converted into a false PASS.
2. `scripts/run_b6q_checkvintf.py` builds AOSP host `--dirmap`
   arguments for the mixed system and vendor tree, using target first API
   properties. It reports `NOT_RUN_CHECKVINTF_MISSING` if not installed,
   and never authorizes flashing even if host compatibility passes.
3. `scripts/diagnose_b6q_all.py` includes this host VINTF phase in the
   same one-command ZIP collection. No new screenshots required.
4. Synthetic unit tests validate success, missing HAL, unknown matrix,
   absent host checker, incompatible checker return, and safe read-only
   behavior.

Official checkvintf usage reference:
https://android.googlesource.com/platform/system/libvintf/+/main/check_vintf.cpp

## Priorities before a flashable Odin AP

1. **Complete VINTF:** run host `checkvintf` with correct device SKU,
   framework vendor/odm manifests and all APEX/kernel information.
   Name-level match is not a substitute.
2. **First-stage boot:** inspect target F741N vendor_boot/init_boot/boot
   images and ramdisk fstab, matching the target dynamic partitions.
3. **SELinux and vendor HAL ABI:** validate combined policy, init services,
   binary/NDK/VNDK symbol and version requirements.
4. **AVB:** prove how altered system/product/system_ext would be accepted by
   target boot chain without misleading stock signatures.
5. **Recoverable validation:** only after above, design a test with verified
   model-specific stock restore and backup, then separately test boot,
   DeX, 120 Hz mirror/DeX modes, fold state, radio, peripherals.

No Odin AP was created or tested as part of these reviews. Never use F956N
bootloader, modem, kernel, dtbo, vendor or vbmeta on F741N.

## Host preservation

The uploaded diagnostic showed local changes in
`external/kernel` and `external/erofs-utils`. Do **not** reset/clean these
submodules as a routine part of the port; preserve the existing work tree.


## 2026-11-18 — boot format and first-stage mount gate added

The preflight now includes `scripts/audit_b6q_boot_mount_gate.py`, wired into
`scripts/diagnose_b6q_all.py` (one-command ZIP collection). This read-only
gate:
- checks staged stock F741N `boot.img` and `init_boot.img` v3/v4 headers;
- parses the F741N `vendor_boot.img` v3/v4 header, vendor ramdisk table
  fragment offsets, sizes, types, and names without extracting ramdisk content;
- compares stock F741N vendor/odm `fstab.*` rules for all seven planned
  dynamic mount points with `logical`, `first_stage_mount`, and `avb`;
- displays stock BL AVB descriptor overlap with changed F956N system partitions.

All outputs remain `flashable=false` and `bootable=false`, including if the
fstab structure is consistent. This is **not** a full first-stage ramdisk,
kernel DTB or AVB signature validation. Inspecting these structures is
only an evidence-gathering gate and does not authorize Odin flashing.

On the user's Debian host, refresh the branch and regenerate the ONE-ZIP
diagnostic bundle:

```bash
cd ~/OnigiriDeX && git pull --ff-only && python3 scripts/diagnose_b6q_all.py
```

Only share the resulting ZIP under `out/b6q/diagnostics`. Do not attach
stock Odin firmware images, partition images, certificates, or any private
cryptographic keys.

## 2026-11-18 — results from updated one-shot F741N diagnostic ZIP

Analyzed user-supplied ZIP dated 2026-11-18, generated with
\`audit-f741n-vbmeta-chain-20261118\` commit \`9a38aba\`.

- Stock F741N \`boot.img\`: header v4; kernel bytes 36,952,576; ramdisk 0.
- Stock F741N \`init_boot.img\`: header v4; ramdisk 1,716,724 bytes.
- Stock F741N \`vendor_boot.img\`: header v4, page size 4096; vendor ramdisk
  14,947,477 bytes; DTB 6,793,838 bytes; bootconfig 198 bytes; one v4
  ramdisk fragment (type 1, offset 0; fragment name empty).
- All seven selected original F741N stock boot files match stage manifest.
- Stock \`vendor/etc/fstab.qcom\` has EROFS variants with \`logical\`,
  \`first_stage_mount\` and \`avb\` for all seven selected dynamic partitions.
  This is a format check, not proof that the kernel mounts them at boot.
- AVB stock BL hashtree descriptors include \`system\`, \`product\`,
  \`system_ext\`; rebuilt images must not be presumed accepted by that chain.
- AOSP host \`checkvintf\` was not installed; official host
  compatibility check has NOT run.
- F741N vendor device matrix mandatory HAL name check was 5/5; it remains
  only a name-level comparison.
- Rebuilt super engineering preview exists (10,093,443,080 bytes) with SHA256
  record; the full 10 GB file has NOT been rehashed in this diagnostic run.

### New source work after reviewing the ZIP

\`scripts/inspect_b6q_stock_ramdisks.py\` now performs bounded read-only
examination of the existing original F741N \`init_boot\` and \`vendor_boot\`
ramdisk sections. Supports gzip, LZ4, and uncompressed newc CPIO; gathers
only filenames, sizes and dynamic fstab flags, never packages ramdisk binaries
into an output ZIP.

This is integrated into \`scripts/diagnose_b6q_all.py\`, with synthetic
tests under \`tests/test_f741n_stock_ramdisk_inspection.py\`.

**Next proof needed**: compare the ramdisk-supplied fstab and init scripts
against the preserved F741N vendor/odm rules, then perform an actual AOSP
host checkvintf run using the correct SKU/APEX/kernel inputs. AVB/SELinux
and bootability remain unresolved even when those steps pass. Do not flash
the preview.
