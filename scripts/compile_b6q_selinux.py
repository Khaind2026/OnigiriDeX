#!/usr/bin/env python3
"""Test mixed F956N system / F741N vendor split SELinux CIL with host secilc.

Uses the Android 15 init fallback compile input order, operating ONLY on the
existing prepared ROM work tree. Writes temporary compiler outputs under a
private scratch directory that is removed. Never installs compiled policy,
modifies firmware, disables SELinux on a phone, signs AVB or enables flashing.

The init-equivalent pass includes -N (skip neverallow validation) because
Android init uses it. A separate STRICT pass omits -N; outcomes are reported
independently and neither constitutes real device boot compatibility.
AOSP: platform/system/core/init/selinux.cpp (Android 15).
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from audit_b6q_selinux_inputs import inspect, select_root

POLICY_VERSION = 30  # Android 15 AOSP SEPOLICY_VERSION; not FCM level or vendor API.
MAX_CIL_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 192 * 1024 * 1024


def add_cil(selected, label, file, required=False):
    if file is None or file.is_symlink() or not file.is_file():
        if required:
            raise ValueError("Missing required SELinux CIL: " + label)
        return False
    size = file.stat().st_size
    if size <= 0 or size > MAX_CIL_BYTES:
        raise ValueError("Invalid SELinux CIL size: " + label)
    selected.append((label, file, size))
    return True


def policy_inputs(work):
    triage = inspect(work)
    if triage.get("vendor_policy_version_error"):
        raise ValueError(triage["vendor_policy_version_error"])
    version = triage.get("stock_f741n_vendor_policy_version")
    if not version or not triage.get("donor_system_compat_mapping_found"):
        raise ValueError("Donor system does not contain the target vendor policy mapping")
    roots = {p: select_root(work, p) for p in ("system", "system_ext", "product", "vendor", "odm")}
    if not roots["system"] or not roots["vendor"]:
        raise ValueError("Missing F956N system or F741N vendor partition root")
    sel = {k: (v / "etc/selinux" if v else None) for k, v in roots.items()}
    selected = []
    p = lambda k, name: sel[k] / name if sel[k] else None
    add_cil(selected, "system/plat_sepolicy.cil",
            p("system", "plat_sepolicy.cil"), required=True)
    add_cil(selected, "system/mapping/" + version + ".cil",
            p("system", "mapping/" + version + ".cil"), required=True)
    add_cil(selected, "system/mapping/" + version + ".compat.cil",
            p("system", "mapping/" + version + ".compat.cil"))
    add_cil(selected, "system_ext/system_ext_sepolicy.cil",
            p("system_ext", "system_ext_sepolicy.cil"))
    add_cil(selected, "system_ext/mapping/" + version + ".cil",
            p("system_ext", "mapping/" + version + ".cil"))
    add_cil(selected, "system_ext/mapping/" + version + ".compat.cil",
            p("system_ext", "mapping/" + version + ".compat.cil"))
    add_cil(selected, "product/product_sepolicy.cil",
            p("product", "product_sepolicy.cil"))
    add_cil(selected, "product/mapping/" + version + ".cil",
            p("product", "mapping/" + version + ".cil"))
    # Android init treats these two F741N vendor sources as mandatory.
    add_cil(selected, "vendor/plat_pub_versioned.cil",
            p("vendor", "plat_pub_versioned.cil"), required=True)
    add_cil(selected, "vendor/vendor_sepolicy.cil",
            p("vendor", "vendor_sepolicy.cil"), required=True)
    # ODM policy is optional in AOSP init; its absence is not automatically a failure.
    add_cil(selected, "odm/odm_sepolicy.cil", p("odm", "odm_sepolicy.cil"))
    total = sum(size for _, _, size in selected)
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Combined CIL inputs exceed size limit")
    # genfs_labels_version and policy's split APEX inputs are not modeled here;
    # a host success can never be reported as verified boot compatibility.
    return version, selected


def resolve_compiler(work, compiler=None):
    if compiler:
        return str(compiler)
    found = shutil.which("secilc")
    if found:
        return found
    repo = work.resolve()
    for folder in repo.parents:
        for suffix in ("out/tools/bin/secilc", "out/host/linux-x86/bin/secilc"):
            candidate = folder / suffix
            if candidate.is_file() and not candidate.is_symlink():
                return str(candidate)
    return None


def classify_strict_failure(phase):
    """Expose only a bounded category, never raw CIL or host paths."""
    if not isinstance(phase, dict):
        return "NOT_RUN"
    status = phase.get("status")
    if status == "COMPILED":
        return "PASSED"
    if status == "ERROR":
        if phase.get("reason") == "TimeoutExpired":
            return "COMPILER_TIMEOUT"
        return "COMPILER_EXECUTION_ERROR"
    if status != "FAILED":
        return "NOT_RUN"
    output = (str(phase.get("stderr_tail", "")) + "\n" +
              str(phase.get("stdout_tail", ""))).lower()
    if "neverallow" in output:
        return "NEVERALLOW_VIOLATION_DETECTED"
    if any(word in output for word in (
            "unknown type", "unknown role", "unknown attribute",
            "undefined", "unresolved", "failed to resolve", "not declared")):
        return "UNRESOLVED_POLICY_SYMBOL"
    if any(word in output for word in (
            "syntax error", "invalid cil", "failed to parse", "parse error")):
        return "CIL_SYNTAX_ERROR"
    return "OTHER_STRICT_COMPILATION_FAILURE"


def compile_policy(work, compiler=None, timeout=120):
    result = {
        "target": "SM-F741N", "donor": "SM-F956N",
        "phase": "READ_ONLY_HOST_SPLIT_SELINUX_COMPILE",
        "status": "NOT_RUN",
        "flashable": False, "bootable": False,
        "compiler_semantics": "Android 15 split SELinux CIL, -c 30, -m -M true -G; init pass -N",
        "notes": [
            "Init-equivalent -N means neverallow rules are NOT validated in that pass",
            "Separate strict pass without -N is recorded, not treated as Android runtime proof",
            "Does not test precompiled vendor policy digests, genfs label version or APEX SELinux",
            "No policy is installed or used to modify a ROM image or the phone",
        ],
    }
    try:
        version, files = policy_inputs(work)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["status"] = "NOT_RUN_INCOMPLETE_POLICY_INPUTS"
        result["reason"] = str(exc)[:500]
        return result

    result["vendor_policy_version"] = version
    result["inputs"] = [{"label": label, "bytes": size} for label, _, size in files]
    binary = resolve_compiler(work, compiler)
    if not binary:
        result["status"] = "NOT_RUN_SECILC_MISSING"
        return result

    all_inputs = [str(path) for _, path, _ in files]
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="f741n-selinux-compile-") as tmp:
        scratch = Path(tmp)
        for phase, no_neverallow in (("init_equivalent", True), ("strict_neverallow", False)):
            out = scratch / (phase + ".sepolicy")
            args = [str(binary), "-m", "-M", "true", "-G"]
            if no_neverallow:
                args.append("-N")
            args += ["-c", str(POLICY_VERSION), "-o", str(out),
                     "-f", "/dev/null", *all_inputs]
            try:
                proc = subprocess.run(args, capture_output=True, text=True,
                                      timeout=timeout, check=False)
                outcomes[phase] = {
                    "status": "COMPILED" if proc.returncode == 0 else "FAILED",
                    "exit_code": proc.returncode,
                    "stdout_tail": proc.stdout[-2500:],
                    "stderr_tail": proc.stderr[-7000:],
                    "binary_bytes": out.stat().st_size if out.is_file() else 0,
                }
            except (OSError, subprocess.TimeoutExpired) as exc:
                outcomes[phase] = {"status": "ERROR", "reason": type(exc).__name__}
    result["passes"] = outcomes
    init_status = outcomes["init_equivalent"]["status"]
    strict_status = outcomes["strict_neverallow"]["status"]
    result["strict_pass_status"] = strict_status
    result["strict_failure_category"] = classify_strict_failure(
        outcomes["strict_neverallow"]
    )
    result["status"] = (
        "HOST_SELINUX_COMPILE_PASSED_RUNTIME_UNVERIFIED"
        if init_status == "COMPILED" else
        "HOST_SELINUX_COMPILE_FAILED" if init_status == "FAILED" else
        "HOST_SELINUX_COMPILE_ERROR"
    )
    result["neverallow_check"] = (
        "PASSED_HOST_ONLY" if strict_status == "COMPILED" else
        "FAILED_HOST_ONLY" if strict_status == "FAILED" else
        "NOT_VERIFIED_HOST_ONLY"
    )
    return result


def main(argv=None):
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path,
                        default=repo / "out/target/b6q/SM-F741N/work_dir")
    parser.add_argument("--tool", default=None, help="Optional local secilc binary")
    parser.add_argument("--output", type=Path,
                        default=repo / "out/b6q/analysis/f741n-f956n-secilc-host-compile.json")
    args = parser.parse_args(argv)
    try:
        report = compile_policy(args.work_dir, args.tool)
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Refusing to overwrite diagnostic report")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, "SELinux host compile error: " + str(error) + "\n")
    print("F741N/F956N SELinux:", report["status"])
    print("Host neverallow:", report.get("neverallow_check", "NOT_RUN"))
    print("Report:", args.output)
    print("No ROM image or device has been modified. No Odin AP. DO NOT FLASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
