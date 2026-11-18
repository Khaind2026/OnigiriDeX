#!/usr/bin/env python3
"""Inspect SELinux policy cross-version inputs for the F956N -> F741N ROM.

Offline, read-only checks of the already extracted source/vendor tree.
Checks policy fragments and vendor plat_sepolicy_vers mapping presence.
No policy compilation, SELinux disabling, image patching, or flash.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

TARGET = "SM-F741N"
DONOR = "SM-F956N"
PARTITIONS = ("system", "product", "system_ext", "vendor", "odm",
              "vendor_dlkm", "system_dlkm")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
MAX_VERSION_BYTES = 256

FRAGMENTS = {
    "system": ("etc/selinux/plat_sepolicy.cil", "etc/selinux/plat_file_contexts"),
    "vendor": ("etc/selinux/vendor_sepolicy.cil", "etc/selinux/vendor_file_contexts"),
    "system_ext": ("etc/selinux/system_ext_sepolicy.cil",),
    "product": ("etc/selinux/product_sepolicy.cil",),
    "odm": ("etc/selinux/odm_sepolicy.cil",),
}
ROOTS = {
    "system": ("system/system", "system"),
    "product": ("product", "product/product"),
    "system_ext": ("system_ext", "system_ext/system_ext"),
    "vendor": ("vendor", "vendor/vendor"),
    "odm": ("odm", "odm/odm"),
}


def select_root(work, part):
    matches = []
    for relative in ROOTS[part]:
        candidate = work / relative
        if candidate.is_dir() and not candidate.is_symlink() and (candidate / "etc").is_dir():
            matches.append(candidate)
    if len(matches) > 1:
        with_selinux = [x for x in matches if (x / "etc/selinux").is_dir()]
        if len(with_selinux) == 1:
            matches = with_selinux
    return matches[0] if len(matches) == 1 else None


def inspect(work):
    if work.is_symlink() or not work.is_dir():
        raise ValueError("F741N work tree missing")
    origin = work / "port-origin.json"
    if origin.is_symlink() or not origin.is_file():
        raise ValueError("F741N origin manifest missing")
    data = json.loads(origin.read_text(encoding="utf-8"))
    if data.get("target") != TARGET or data.get("donor") != DONOR:
        raise ValueError("Unexpected F741N/F956N firmware source mapping")
    if not (work / ".b6q-prepared").is_file():
        raise ValueError("Expected staged b6q work tree")

    results = {}
    roots = {}
    for part in ROOTS:
        directory = select_root(work, part)
        roots[part] = directory
        files = {}
        for name in FRAGMENTS[part]:
            p = directory / name if directory is not None else None
            files[name] = bool(p and p.is_file() and not p.is_symlink())
        results[part] = {
            "partition_root_found": directory is not None,
            "policy_fragments": files,
        }

    # The stock vendor's policy version determines which framework mapping
    # file is expected. The donor framework cannot simply be assumed compatible.
    vendor = roots["vendor"]
    vers = vendor / "etc/selinux/plat_sepolicy_vers.txt" if vendor else None
    version = None
    version_error = None
    if not vers or vers.is_symlink() or not vers.is_file():
        version_error = "F741N vendor plat_sepolicy_vers.txt not found"
    elif vers.stat().st_size > MAX_VERSION_BYTES:
        version_error = "F741N vendor policy version exceeds bound"
    else:
        version = vers.read_text(encoding="ascii", errors="replace").strip()
        if not VERSION_PATTERN.fullmatch(version):
            version_error = "Invalid F741N policy version"
            version = None
    system = roots["system"]
    mapping = system / "etc/selinux/mapping" / (version + ".cil") if system and version else None
    mapping_found = bool(mapping and mapping.is_file() and not mapping.is_symlink())

    fs_configs = {}
    for part in PARTITIONS:
        path = work / "configs" / ("file_context-" + part)
        fs_configs[part] = bool(path.is_file() and not path.is_symlink() and path.stat().st_size > 0)

    missing_required = []
    for part in ("system", "vendor"):
        for filename, present in results[part]["policy_fragments"].items():
            if not present:
                missing_required.append(part + "/" + filename)
    if not all(fs_configs.values()):
        missing_required.extend("configs/file_context-" + k
                                for k, present in fs_configs.items() if not present)

    if version_error or not all(roots[k] for k in ("system", "vendor")):
        status = "UNKNOWN_SELINUX_POLICY_VERSION_OR_LAYOUT"
    elif not mapping_found:
        status = "BLOCKED_F741N_VENDOR_TO_F956N_SYSTEM_MAPPING_MISSING"
    elif missing_required:
        status = "INCOMPLETE_SELINUX_POLICY_COMPONENTS"
    else:
        status = "SELINUX_FILES_PRESENT_COMBINED_POLICY_NOT_VERIFIED"

    return {
        "target": TARGET,
        "donor": DONOR,
        "phase": "READ_ONLY_COMBINED_SELINUX_INPUT_TRIAGE",
        "status": status,
        "stock_f741n_vendor_policy_version": version,
        "vendor_policy_version_error": version_error,
        "donor_system_compat_mapping_found": mapping_found,
        "donor_compat_mapping": str(mapping.relative_to(work)) if mapping else None,
        "policy_components": results,
        "file_contexts_present": fs_configs,
        "missing_required_components": missing_required,
        "secilc_available": bool(shutil.which("secilc")),
        "unresolved": [
            "A matching filename is NOT proof of valid mapping statements",
            "No actual combined sepolicy compilation or neverallow validation",
            "No init/vendor service domain or runtime audit2allow review",
            "No system/vendor APK and native HAL ABI verification",
        ],
        "flashable": False, "bootable": False,
    }


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path,
                        default=repo / "out/target/b6q/SM-F741N/work_dir")
    parser.add_argument("--output", type=Path,
                        default=repo / "out/b6q/analysis/f741n-f956n-selinux-triage.json")
    args = parser.parse_args(argv)
    try:
        result = inspect(args.work_dir)
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Report exists; refusing overwrite")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "SELinux triage failed: " + str(exc) + "\n")
    print("F741N vendor plat policy version:", result["stock_f741n_vendor_policy_version"])
    print("F956N matching framework mapping:", result["donor_system_compat_mapping_found"])
    print("STATUS:", result["status"])
    print("Report:", args.output)
    print("No firmware modified. No Odin AP. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
