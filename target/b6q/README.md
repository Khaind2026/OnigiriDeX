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
