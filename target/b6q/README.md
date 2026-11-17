# DuyKhaiDeX experimental target: Samsung Galaxy Z Flip6 (b6q)

**Research-only scaffold. No validated build, no Odin AP and no safe flash output.**

This directory is intentionally NOT wired into the existing
`buildenv.sh`, `make_rom.sh`, or `build_odin.sh` Flip5 (`b5q`) workflow.

## Pinned inputs

- Hardware target: SM-F741N (SKC), F741NKSS2BYGB, Android 15 / One UI 7
- System donor: SM-F956N (SKC), F956NKSS2BYGB, Android 15 / One UI 7
- Config: `port-plan.json` supplies source mapping (Fold6 system-side
  `system/product/system_ext`, Flip6 hardware `vendor/odm/*_dlkm`).
- Use original F741N boot/vendor_boot/init_boot/dtbo/recovery/AVB/BL/CP
  only once separately validated. Do not cross-flash F956N low-level images.

## Completed analyses

1. Verified Odin archive names and MD5 trailers on the user's host.
2. Both AP packages contain Samsung `super.img.lz4`.
3. `inspect_super_f741n_f956n.py` confirms LP 10.0, seven partitions,
   group `qti_dynamic_partitions` on each stock image.
4. `plan_f741n_f956n_port.py` computes a read-only estimate of hybrid
   partition occupancy against **F741N**'s group maximum.

Run `python3 scripts/plan_f741n_f956n_port.py` after generating
`out/reports/f741n-f956n-super-metadata.json` on the user's Debian host.

## Required milestones

- Obtain the actual phone's model, bootloader revision and vendor kernel ABI.
- Inspect exact stock super metadata and candidate hybrid image composition.
- Build independently extracted *matching* target vendor/odm and donor
  system/product/system_ext into isolated b6q work directories.
- Check framework/vendor VINTF, SELinux, permissions, proprietary libraries,
  PackageManager and display-related services.
- Rebase DeX and outer-display patches against **F956N One UI 7** decompiled
  files. Existing Fold5 APK/JAR binary patches must **not** be applied blind.
- Confirm super sizes, target AVB/boot chain, recovery and rollback plan.
- Only then add explicit b6q build+Odin validation and device testing.

A positive capacity estimate is NOT proof that DeX works or that a ROM boots.
Upstream license, NOTICE, copyrights, and appropriate author credits are
preserved even when the display branding is DuyKhaiDeX.


## Phase 4: staged stock partition extraction

The user's real LP report produced **Capacity estimate: PASS**:
F741N group maximum 13,196.0 MiB; donor-system/target-hardware
estimated occupancy 10,774.0 MiB, leaving 2,422.0 MiB. This is a
space estimate, not a successful firmware build.

Run these **read-only preflight** checks before allocating large images:

```bash
cd ~/OnigiriDeX
git pull --ff-only
export PATH="$PWD/out/tools/bin:$PATH"
python3 scripts/extract_b6q_images.py --model SM-F956N
python3 scripts/extract_b6q_images.py --model SM-F741N
```

The script prints free storage, estimated maximum required storage, and selected
partitions for each model. By default it creates no image files and does not
use the phone. It requires `lz4` and `lpunpack`, and uses existing verified
Odin imports and `out/reports/f741n-f956n-super-metadata.json`. It
**refuses to overwrite** existing extracted output.

Only if preflight reports sufficient free storage, use **explicit** extraction,
one model at a time:

```bash
python3 scripts/extract_b6q_images.py --model SM-F956N --extract
python3 scripts/extract_b6q_images.py --model SM-F741N --extract
```

Result paths:
`out/b6q/extracted/SM-F956N/{system,product,system_ext}.img` and
`out/b6q/extracted/SM-F741N/{vendor,odm,system_dlkm,vendor_dlkm}.img`,
alongside a per-device `manifest.json`.

For each model the tool streams stock `super.img.lz4` from the matching
archive into a **temporary** raw super file, unpacks only selected images
using `lpunpack -p`, checks extracted byte sizes against LP metadata,
and publishes a complete model folder only when checks pass.
Temporary files are cleaned if extraction fails. Never run both extractions
concurrently on limited storage. Keep original firmware on drive D mounted.

**No** b6q system builder, Samsung APK/JAR DeX port, Odin AP, or tested ROM
is produced by this tool. Do not flash images from this staging directory.


## Phase 5: verify completed extraction

After BOTH per-model extraction commands have returned successfully to the
shell prompt, verify all seven staged stock filesystem images without writing
to their content:

```bash
cd ~/OnigiriDeX
git pull --ff-only
python3 scripts/verify_b6q_stage.py
```

Expected extracted source split:
- F956N: `system.img`, `product.img`, `system_ext.img`
- F741N: `vendor.img`, `odm.img`, `system_dlkm.img`, `vendor_dlkm.img`

Validation compares each file's size to the matching LP metadata and
manifest, checks model selection and simple filesystem signatures.
Optional `--sha256` hashes all 7 files for a reproducible image inventory.
Report: `out/reports/f741n-f956n-stage-validation.json`.

The script is intentionally read-only and is *not* a flashability, DeX,
VINTF, SELinux, boot or Android framework compatibility test.
If the Fold6 extraction has not yet returned a prompt, do not run an
additional extraction concurrently in the same terminal.
