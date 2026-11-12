# Build DK điều chỉnh for both Galaxy Z Flip5 models

This helper builds two separate Odin AP archives: SM-F731B (international/XXV) and SM-F731N (Korea/KOO). Both use the same custom kernel, built once. Do not use the resulting AP on another model.

## Requirements

- Linux with Bash, Python 3, Java and the native Android build dependencies listed in .github/workflows/release.yml. This release workflow uses Debian 13 / OpenJDK 21. On Windows, run an appropriate Linux build environment (such as WSL2 Debian 13), not PowerShell directly.
- Plenty of time and disk space (plan for 150 GiB free or more for a first build). Keep the checkout on a Linux filesystem rather than /mnt/c for performance.
- Clone with all submodules: git clone --recurse-submodules https://github.com/Khaind2026/OnigiriDeX.git
- Three FULL original Samsung firmware ZIP archives containing AP, BL, CP, CSC, matching the versions pinned in onigiri/configs/firmware.json.

Required versions:

- SM-F731B / XXV: F731BXXS5EYI1
- SM-F731N / KOO: F731NKSS5EYGB
- SM-F946B / XXV donor: F946BXXS5EYI1
- Optional SM-S921B / XXV: S921BXXS9BYH1 (additional display-colour assets).

## Run locally

From the checkout root, run:

    bash scripts/build_dk_both_flip5.sh /path/F731B.zip /path/F731N.zip /path/F946B.zip

Optionally pass the S24 ZIP as a fourth argument. The archive path may point to /mnt/d/... when accessing Windows files from WSL2.

### Directly using unpacked firmware (no ZIP needed)

If the three firmware sets are already unpacked on the Windows D: drive into AP, BL, CP and CSC tar.md5 files, use their **directory paths** instead:

```bash
bash scripts/build_dk_both_flip5.sh \
  '/mnt/d/FLip5/SAMFW.COM_SM-F731B_XXV_F731BXXS5EYI1_fac' \
  '/mnt/d/FLip5/SAMFW.COM_SM-F731N_SKC_F731NKSS5EYGB_fac' \
  '/mnt/d/f5/SAMFW.COM_SM-F946B_XXV_F946BXXS5EYI1_fac'
```

The F731N directory may be labeled SKC by the download source, while its Odin CSC package is `CSC_OKR_F731NOKR5EYGB_...`; the package names inside the folder must match the pinned versions. Directory names themselves are not trusted as proof of validity.


For a complete ZIP, scripts/import_fw.py checks the ZIP's pinned MD5 and the internal Odin checksums. For extracted directories, scripts/import_fw_dir.py requires matching AP, BL, CP and CSC filenames/versions and validates each .tar.md5 package's own MD5 before making links (no duplicate large file copies). It cannot check the MD5 of the original ZIP because the ZIP is not supplied. Keep the firmware directories on the D: drive accessible until extraction is complete. If the versions or checksums do not match, the script stops.

The helper builds dependencies, imports and extracts the firmware, builds the shared kernel, and creates one AP for SM-F731B and one for SM-F731N using the repository's existing onigiri build_odin path.

Successful outputs appear in out/ with names matching:

- Onigiri_AP_SM-F731B_*.tar.md5
- Onigiri_AP_SM-F731N_*.tar.md5

Each output's SHA-256 is printed. The files are NOT produced merely by adding this helper to GitHub: the build must actually finish on the Linux host.

## GitHub Actions release caveat

The existing .github/workflows/release.yml can build both models on a pushed tag, but requires a PRIVATE draft release with tag firmware containing the pre-extracted out/fw archives and the ONIGIRI_SIGNING_KEYS Actions secret. Just uploading raw firmware ZIPs into a release is not sufficient. See docs/releasing.md.

Back up the locally generated security/onigiri_platform.* and security/onigiri_ota.* keypairs. Do not put private keys, Samsung firmware archives, or other copyrighted binary firmware in the public Git repository. Use only software and firmware you are authorized to modify.

Use the corresponding model's factory BL/CP/CSC for installation and keep full original firmware and data backups. Building does not guarantee the resulting ROM has been tested on real hardware.
