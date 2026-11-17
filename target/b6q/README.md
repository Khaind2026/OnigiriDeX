# DuyKhaiDeX experimental target: Samsung Galaxy Z Flip6 (b6q)

## Direct b5q → b6q ROM port driver (current route)

This port now **reuses the working Flip5 OnigiriDeX build architecture**
instead of building more inventory utilities. It selects original stock
EROFS images already extracted by the user's Debian machine, invokes
`EXTRACT_EROFS_PARTITION` from `scripts/utils/firmware_utils.sh`, and
replays the exact Flip5 DeX smali patch tree through the existing
`scripts/internal/apply_modules.sh` and `scripts/apktool.sh` pipeline.
The device-specific b6q DeX module follows the exact `module.prop` +
`customize.sh` structure from b5q.

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/port_b6q.sh all
```

The first run creates `out/target/b6q/SM-F741N/work_dir` using:
- `system`, `product`, `system_ext` from **F956N (Fold6)**
- `vendor`, `odm`, `system_dlkm`, `vendor_dlkm` from **F741N (Flip6)**

The script then applies native DeX feature flags and **tries the actual
b5q services.jar / DesktopSystemUI / SystemUI / SmartCapture smali patches**
against the Fold6 binaries, compiling with the original apktool pipeline.
A patch incompatibility stops immediately and records the failing hunk in
`out/b6q/port-logs`; the prepared work directory is preserved. There is
no need to download, inspect, or stage firmware again.

`bash scripts/port_b6q.sh prepare` can be used by itself for work-tree
preparation, and `bash scripts/port_b6q.sh apply` runs the patch step.

**Important constraints:** The original b5q native SurfaceFlinger patch
checks a Fold5-specific SHA-256 and hard-coded instruction offsets. The b6q
module intentionally does not copy that native binary patch, Flip5-specific
vendor SELinux rule, camera HAL offset, or cover-screen geometry. They must
be **rebased to F956N/F741N**, not flashed blindly. This route produces a
port work directory, NOT a fully tested/bootable Odin AP. Upstream license
and credits remain in place.

---

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


## Phase 6: inspect Samsung DeX-related framework/vendor files

After a successful `Stage verification PASS` of the seven EROFS images,
perform a **read-only selective audit** (not another full image extraction):

```bash
cd ~/OnigiriDeX
git pull --ff-only
export PATH="$PWD/out/tools/bin:$PATH"
python3 scripts/audit_b6q_framework.py
```

The audit reads small stock properties and VINTF XML files via
`dump.erofs --cat --path=...`, and lists selected framework, app and HAL
directories via `dump.erofs --ls --path=...`. It searches those names for
DeX, desktop, display, WindowManager, SystemUI, HDMI and Knox-related
components without modifying any EROFS image. Absent optional paths are
reported as missing instead of silently inventing compatibility evidence.

Report: `out/reports/f741n-f956n-framework-audit.json`.
Before building, review the complete report, verify Android SDK/vendor API
and VINTF HAL versions across the target and donor, and inspect the exact
Fold6 APK/JAR resource IDs before rebasing existing Onigiri DeX patches.
The audit does **not** establish that DeX is enabled or ROM is bootable.
If the installed `dump.erofs` lacks `--cat` or `--path`, record the
version and help output instead of extracting everything blindly.


## Phase 7: inspect exact DeX candidates from the framework audit

The user's 2026-11-18 output confirmed the 7 staged EROFS images pass
validation. Fold6 reports SDK 35 and Flip6 vendor reports device `b6q`
with `ro.vendor.build.version.sdk=34`; the latter alone does not imply
framework/vendor incompatibility.

Read the existing audit JSON rather than extracting images again:

```bash
cd ~/OnigiriDeX
git pull --ff-only
python3 scripts/report_b6q_dex_candidates.py
```

This prints all DeX/desktop/display candidate listing matches and checks
whether three original Fold5 DeX app names appear in the Fold6 listing
(`KnoxDesktopLauncher`, `DesktopModeUiService`, `DesktopSystemUI`),
along with corresponding permission XML names. Missing matches only mean
"not seen in this limited directory listing", **not** that the component
is absent or incompatible. It also summarizes selected VINTF/HAL names.

Output is `out/reports/f741n-f956n-dex-candidates.json`.
Before patching any APK/JAR, inspect and compare actual executable resources
and vendor interfaces; do not apply Fold5 binary patch offsets or SELinux
policy substitutions directly to Fold6 framework/Flip6 vendor.


## Phase 8: build F741N super engineering preview using original b5q packer

The user's Debian terminal confirmed all original b5q DeX smali patches replayed
onto F956N, then `SmartCapture.apk`, `SystemUI.apk`,
`DesktopSystemUI.apk`, and `services.jar` were successfully rebuilt.
`out/target/b6q/SM-F741N/work_dir/.b6q-dex-patched` is now present.

The next step **reuses exactly the same build pipeline as
`scripts/build_odin.sh`**: `scripts/build_fs_image.sh erofs`,
`lpmake`, `simg2img`, `lpunpack`, and byte-for-byte checks.
It uses real SM-F741N super geometry rather than b5q's hardcoded sizes.

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/build_super_b6q.sh
bash scripts/build_super_b6q.sh --build
```

Output:
`out/b6q/build/DuyKhaiDeX_F741N_SUPER_PREVIEW_NOT_FOR_FLASH.img`
plus .sha256 and .txt notes. It is a **non-flashable engineering preview**:
the F741N boot images, AVB descriptors, recovery and required vendor/framework
compatibility checks are not done. The previous b5q binary SurfaceFlinger
offsets cannot be reused on F956N. The common Onigiri Settings UI and no-SIM
branding patches still need to be replayed separately on the b6q source tree
before a release candidate, even though their source text has been renamed.
No ROM has been boot-tested on the user's Flip6.

The preview packs **all seven** partitions from the *already prepared and
DeX-patched work directory*, without re-downloading or re-extracting firmware.
It will refuse to overwrite existing preview output.


## Phase 9: apply original Settings branding patches without losing the preview

The user's 2026-11-18 Debian output confirms
`ENGINEERING SUPER PREVIEW BUILT AND RE-UNPACK VERIFIED` after repacking
all seven b6q partitions. Later `Output already exists; refusing overwrite`
messages are expected protections, not build failures. The repeated
`Invalid sparse file format at header magic` messages were non-fatal during
this run; the final `lpunpack` + `cmp` verified the generated preview.

To port the **original Onigiri Settings** UI and carrier text, reusing the
real patch series on the already DeX-patched F956N APK/JAR files:

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh
```

This script replays `onigiri/mods/settings/smali` via the existing module
and apktool build pipeline. It does not copy the original Fold5
`customize.sh` that changes vendor SELinux policy. The upstream patch
source already contains "Duy Khải Điều Chỉnh" and
"Duy Khải DeX 0862134811" display strings. A Fold6 patch mismatch
stops with a detailed log in `out/b6q/port-logs` and retains the
work tree for a targeted fix. No need to re-import or re-extract firmware.

The existing DeX-only `DuyKhaiDeX_F741N_SUPER_PREVIEW_NOT_FOR_FLASH.img`
will remain untouched. **After** a complete Settings patch replay,
`bash scripts/build_super_b6q.sh --build` writes a NEW separate file
named `DuyKhaiDeX_F741N_BRANDED_SUPER_PREVIEW_NOT_FOR_FLASH.img`.

Both are engineering previews only; **do not flash**. Neither contains
a completed F741N AVB/boot-chain compatibility solution or a
device-tested Odin AP. Preserve upstream license and credits.


### 2026-11-18: resume F956N Settings after missing en-rCA locale

On the user's Debian host, the original Settings replay stopped at its first
SystemUI patch because F956N lacks `res/values-en-rCA/strings.xml`.
The original `git apply` is all-or-nothing for that patch, so this first
attempt made **no Settings patch changes**. The previously verified
DeX-only super preview is untouched.

A Fold6-specific adapter now checks each decoded APK/JAR before applying
a copied upstream patch. **Only** diff sections editing an *absent existing*
`res/values-*/strings.xml` are omitted. It never drops smali, public
resource IDs, XML other than optional locale strings, or new-file patches.
The upstream OnigiriDeX patch files remain intact.

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh --resume
```

`--resume` verifies the previous log was the first-patch missing-locale
failure; later retries use a SHA-pinned ledger at
`out/target/b6q/SM-F741N/work_dir/.b6q-settings-patch-progress`
to skip only upstream patches already applied successfully.
If a Fold6 smali or critical resource hunk differs, replay stops and records
its exact mismatch in `out/b6q/port-logs`. Do not reset the 7 source
images, overwrite the existing super, or blindly skip the failing smali.

Only after `DuyKhaiDeX b6q Settings/brand patch replay completed` may a
**separate** branded engineering super preview be rebuilt using
`bash scripts/build_super_b6q.sh --build`. This is still not a flashable ROM.

### Resume fix: old log-line guard removed (2026-11-18)

The user's following attempt was rejected with
`Prior patch state cannot be verified as atomic first-patch failure.`
The old script incorrectly required a log to have one exact
`^- Applying ` line; log formatting is not a reliable measure of
whether a patch was committed. This was a **runner guard bug**, not a
new firmware or Samsung DeX error.

The b6q Settings runner now checks each pending, adapted original patch
directly against the decoded F956N APK/JAR via
`git apply --check` (not yet applied) and
`git apply --reverse --check` (already applied), with an upstream-file
SHA-pinned per-patch progress ledger. On ambiguous/partial source state
it stops without modifying or rebuilding further files. No deletion of
`.b6q-settings-attempted`, image imports or source tree is necessary.
Run only:

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh --resume
```

This does **not** overwrite the existing verified engineering super
preview or constitute a safe-to-flash ROM.


### Framework.jar prerequisite ordering discovered after Settings replay (2026-11-18)

The user's latest real firmware log confirms:
- Fold6 `SystemUI` no-SIM branding patch **applied**.
- `DAAgent` patch **applied**.
- `framework.jar/0001-Introduce-SamsungPropsHooks.patch` failed on
  `ApplicationPackageManager.smali` and `Instrumentation.smali`.
- The source `SamsungPropsHooks.patch` explicitly anchors its
  Instrumentation edits after `PlayIntegrityHooks->setProps`.
  `onigiri/mods/pif/smali/system/framework/framework.jar/0001-Introduce-PlayIntegrityHooks.patch`
  creates that call. The original `scripts/make_rom.sh` runs
  `onigiri/mods` alphabetically, so **pif precedes settings**.
- The previous b6q Settings-only driver violated that upstream prerequisite
  order, so a failed Settings hunk did not by itself establish a Fold6 ABI
  incompatibility.

`scripts/apply_b6q_settings.sh --resume` now replays the upstream PIF
framework and services smali series first, with the same forward/reverse
dry-run checks and SHA checkpoint ledger, and then resumes the original
Settings patches. It does not claim Play Integrity support or device
security attestation compatibility; such functionality is outside of
the DeX boot-validation milestone.

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh --resume
```

If an upstream PIF patch fails to match the actual F956N smali, the log
identifies the exact unadapted hunk and leaves already applied patches
untouched. Never use `--reject` or unconditional patch fuzz to force
critical framework changes. The existing verified engineering super
preview is unchanged; do not flash it.


### SecSettings F956N SettingsGateway fragment-array rebase (2026-11-18)

The real Fold6 Settings replay now passes `framework.jar`, `knoxsdk.jar`,
`services.jar`, `MultiSoundSetting.apk`, and two earlier SystemUI /
DAAgent Settings patch targets. The next failure is
`system/priv-app/SecSettings/SecSettings.apk/0001-Add-Onigiri-Settings.patch`
at `smali_classes2/com/android/settings/core/gateway/SettingsGateway.smali`.
The old Fold5 patch assumes the Settings gateway fragment array ends at
`v139` and inserts `OnigiriSettingsFragment` as `v140`. The real Fold6
list isn't necessarily identical.

`scripts/rebase_b6q_settings_gateway.py` now generates an exact
Fold6-specific **git diff hunk** from the decoded F956N SettingsGateway,
only in a temporary copy of the original Onigiri patch. It checks one
unambiguous static initializer, a contiguous string array, availability
of the next register, and extends the method register allocation when
needed; all other original patch sections remain unchanged. The patch is
then checked with the same forward/reverse `git apply` guards.

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh --resume
```

Already applied upstream patches are skipped using the existing
SHA-pinned ledger. If the actual F956N method differs too much (e.g. it
uses the next register for another purpose), **the rebase refuses** and
prints a specific reason. No smali, APK or super image is altered by the
rebase tool itself; a successful upstream `git apply` still records the
patch in the ledger. Do not use `git apply --reject` or blindly bump
registers. Previous `super.img` preview remains intact and must not
be flashed.


### SecSettings F956N v141 register collision: append helper (2026-11-18)

The real F956N SettingsGateway initializer already uses v141. The old
Fold5-style attempt to enlarge the v1..v140 array would overwrite it.

The rebase script now keeps the existing Fold6 initializer array and
register allocation untouched when v(N+1) is in use. Immediately after
the anchored array move-result-object, it invokes a private helper
that copies String[] and appends OnigiriSettingsFragment using the
helper's own local registers. Only that result replaces the array in
the same preexisting result register. No patch bypass or fuzzy apply.

Continue without resetting firmware or work directory:

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh --resume
```

The generated patch must still pass git apply on actual F956N smali
and the resulting APK must rebuild successfully before repacking a
new b6q super preview. The earlier preview remains NOT FOR FLASH.


### Fold6 SettingsActivity 0008 registered fragment count (2026-11-18)

After patches 0001..0007 had applied successfully to SecSettings.apk, the
upstream 0008 patch failed at SettingsActivity.smali:967. Original
0008 changes a hardcoded bound (Fold5 0x8b) to array-length for the
SettingsGateway.SAMSUNG_ENTRY_FRAGMENTS field. Fold6's integer bound
or source context can differ, despite equivalent loop behavior.

The direct b6q Settings replay now adapts **only that one instruction**
from the real decoded F956N SettingsActivity.smali. It requires an exact
sget-object -> const -> if-ge -> aget-object loop on matching registers;
if that evidence is missing or ambiguous, the tool refuses without
touching stock files. It then passes the disposable patch to the same
existing git apply dry-run, source patch and SHA ledger checkpoints.

```bash
cd ~/OnigiriDeX
git pull --ff-only
bash scripts/apply_b6q_settings.sh --resume
```

Previous DeX patches, other Settings patch checkpoints and the existing
verified non-flashable engineering super preview remain unchanged.
Success still requires actually rebuilding SecSettings.apk and testing
the eventual b6q ROM on compatible hardware before flashing.
