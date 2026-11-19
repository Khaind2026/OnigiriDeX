# Building the SM-F741N AP candidate

The packaging path now uses the **SM-F741N stock AP** as the Odin container and
keeps its boot, init_boot, vendor_boot, dtbo, vbmeta and recovery images. It
replaces only super.img with the rebuilt hybrid image. Never use the F956N AP
as the container.

From the repository root, after firmware has been imported and the b6q work
tree has been prepared and DeX patches have been applied:

```bash
export PATH="$PWD/out/tools/bin:$PATH"
bash scripts/build_odin_b6q.sh
```

The script finds the one imported `AP_F741N*.tar.md5`, builds the F741N-geometry
super image if absent, verifies the stock Odin MD5, creates the AP archive, and
checks its final Odin MD5. Output:

```
out/DuyKhaiDeX_AP_SM-F741N_CANDIDATE_NOT_FLASH_READY.tar.md5
```

The stock AP must be at `out/odin/SM-F741N_SKC`. If there is more than one F741N
AP there, pass the exact archive path as the first argument.

This output is an **AP candidate**, not a validated flash package. Current
builder keeps the stock F741N vbmeta and boot chain; AVB compatibility,
framework/vendor compatibility, boot, radio, camera, encryption and recovery
have not been verified on a device. Do not flash it until those checks are
completed. The project workspace also needs enough temporary free storage for
the stock AP, rebuilt super and output archive.
