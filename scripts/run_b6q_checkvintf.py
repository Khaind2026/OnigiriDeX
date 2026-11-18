#!/usr/bin/env python3
"""Run official Android host checkvintf against the prepared F956N/F741N tree.

No device access, firmware changes, AP creation, AVB edits, or flashing.
A 0 exit code validates only the selected VINTF host view, not bootability.
Unknown device SKU, APEX VINTF fragments and kernel runtime remain limitations.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

MODEL = "SM-F741N"
DONOR = "SM-F956N"
PARTITION_DIRS = {
    "system": ("system/system", "system"),
    "system_ext": ("system_ext", "system_ext/system_ext"),
    "product": ("product", "product/product"),
    "vendor": ("vendor", "vendor/vendor"),
    "odm": ("odm", "odm/odm"),
}
MAX_PROP_BYTES = 2 * 1024 * 1024


def checked_work_tree(work):
    if work.is_symlink() or not work.is_dir():
        raise ValueError("Missing prepared F741N ROM work tree")
    origin = work / "port-origin.json"
    if origin.is_symlink() or not origin.is_file():
        raise ValueError("Missing F741N port origin manifest")
    obj = json.loads(origin.read_text(encoding="utf-8"))
    if obj.get("target") != MODEL or obj.get("donor") != DONOR:
        raise ValueError("Unexpected F741N/F956N firmware source mapping")
    if not (work / ".b6q-prepared").is_file():
        raise ValueError("Port tree is not marked prepared")


def map_partitions(work):
    mapping = {}
    for part, choices in PARTITION_DIRS.items():
        present = []
        for rel in choices:
            candidate = work / rel
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            present.append(candidate)
        with_vintf = [p for p in present if (p / "etc/vintf").is_dir()]
        if len(with_vintf) == 1:
            mapping[part] = with_vintf[0]
        elif len(with_vintf) > 1:
            raise ValueError(f"Ambiguous {part} VINTF roots")
        elif part in ("system", "vendor"):
            raise ValueError(f"Missing essential {part}/etc/vintf metadata")
        elif len(present) == 1:
            # ODM may have no VINTF XML of its own on stock F741N.
            mapping[part] = present[0]
        else:
            raise ValueError(f"Missing/ambiguous optional {part} partition root")
    return mapping


def first_api_level(vendor_dir):
    prop = vendor_dir / "build.prop"
    if prop.is_symlink() or not prop.is_file() or prop.stat().st_size > MAX_PROP_BYTES:
        raise ValueError("Stock F741N vendor build.prop unavailable/invalid")
    values = {}
    for line in prop.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, val = line.split("=", 1)
        if key in ("ro.product.first_api_level", "ro.board.first_api_level"):
            values[key] = val.strip()
    if not values.get("ro.product.first_api_level", "").isdigit():
        raise ValueError("Missing F741N ro.product.first_api_level")
    return values


def find_host_checkvintf(work):
    """Prefer a real AOSP host binary already built in the user's workspace."""
    binary = shutil.which("checkvintf")
    if binary:
        return binary
    repo = work.resolve().parents[3] if len(work.resolve().parents) >= 4 else None
    if repo is None:
        return None
    # Worktree is <repo>/out/target/b6q/SM-F741N/work_dir.
    if repo.name != "out":
        return None
    root = repo.parent
    for candidate in (
        root / "out/tools/bin/checkvintf",
        root / "out/host/linux-x86/bin/checkvintf",
        root / "out/host/linux-x86/bin/check_vintf",
    ):
        if candidate.is_file() and not candidate.is_symlink():
            return str(candidate)
    return None


def run_check(work, tool=None):
    checked_work_tree(work)
    report = {
        "model": MODEL, "donor": DONOR,
        "phase": "AOSP_HOST_LIBVINTF_CHECK",
        "status": "NOT_RUN",
        "flashable": False,
        "bootable": False,
        "notes": [
            "A host libvintf compatibility check is not a phone boot test",
            "No F741N runtime kernel config or SKU supplied; those checks may be incomplete",
            "APEX VINTF fragments and other partitions beyond the mapped five may be absent",
            "No firmware writes, APK changes, Odin packaging or flashing",
        ],
    }
    try:
        dirs = map_partitions(work)
        props = first_api_level(dirs["vendor"])
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report["status"] = "NOT_RUN_INCOMPLETE_INPUT"
        report["reason"] = str(exc)
        return report

    report["dirmap"] = {"/" + k: str(v) for k, v in dirs.items()}
    report["properties"] = props
    binary = tool or find_host_checkvintf(work)
    if not binary:
        report["status"] = "NOT_RUN_CHECKVINTF_MISSING"
        report["reason"] = "Install/build official AOSP host checkvintf first"
        return report

    command = [str(binary), "--check-compat"]
    for part, folder in dirs.items():
        command.extend(["--dirmap", f"/{part}:{folder}"])
    for prop, value in sorted(props.items()):
        command.extend(["--property", f"{prop}={value}"])
    try:
        completed = subprocess.run(command, cwd=work, capture_output=True,
                                   text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report["status"] = "NOT_RUN_CHECKVINTF_ERROR"
        report["reason"] = str(exc)
        return report
    report["command"] = command
    report["returncode"] = completed.returncode
    report["stdout"] = completed.stdout[-14000:]
    report["stderr"] = completed.stderr[-14000:]
    # AOSP checkvintf: EX_OK (0) + COMPATIBLE is a success;
    # EX_DATAERR (65) + INCOMPATIBLE is a metadata mismatch;
    # EX_SOFTWARE (70) / EX_USAGE (64) are tool/input errors, not proven
    # incompatibility. Never classify a silent zero-exit stub as a PASS.
    stdout_lines = {line.strip() for line in completed.stdout.splitlines()}
    if completed.returncode == 0 and "COMPATIBLE" in stdout_lines:
        report["status"] = "HOST_VINTF_CHECK_PASSED_RUNTIME_UNVERIFIED"
    elif completed.returncode == 65 and "INCOMPATIBLE" in stdout_lines:
        report["status"] = "HOST_VINTF_CHECK_FAILED"
    else:
        report["status"] = "HOST_VINTF_CHECK_TOOL_ERROR"
        report["reason"] = "checkvintf did not return an authoritative AOSP compatibility verdict"
    return report


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path,
                        default=repo / "out/target/b6q/SM-F741N/work_dir")
    parser.add_argument("--tool", default=None,
                        help="Optional path to official AOSP host checkvintf binary")
    parser.add_argument("--output", type=Path,
                        default=repo / "out/b6q/analysis/f741n-f956n-aosp-checkvintf.json")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.exit(1, "Refusing to overwrite report: " + str(args.output) + "\n")
    try:
        report = run_check(args.work_dir, args.tool)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, "VINTF check failed to initialize: " + str(exc) + "\n")
    print("F741N/F956N AOSP VINTF:", report["status"])
    if report.get("reason"):
        print("Reason:", report["reason"])
    print("Report:", args.output)
    print("NO ODIN AP, NO FLASH.")
    return 0 if report["status"] != "HOST_VINTF_CHECK_FAILED" else 2


if __name__ == "__main__":
    sys.exit(main())
