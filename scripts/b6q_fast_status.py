#!/usr/bin/env python3
"""Fast, opt-in PUBLIC GitHub status for DuyKhaiDeX F741N.

Does not create a ZIP or upload files/firmware or device identifiers.
Runs SELinux and VINTF host checks only. A report is shared publicly
ONLY if the user explicitly supplies --publish-public.
"""
import argparse
import datetime
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "out/target/b6q/SM-F741N/work_dir"
REPO = "Khaind2026/OnigiriDeX"
PR = "9"


def safe_status(text):
    if not isinstance(text, str) or not re.fullmatch(r"[A-Z0-9_]{2,110}", text):
        return "UNKNOWN"
    return text


def scrub_errors(raw):
    """Remove paths, emails, possible long secrets and phone-like numbers."""
    s = str(raw)
    s = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)
    s = re.sub(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", "<email>", s)
    s = re.sub(r"(?i)/(?:home|mnt|tmp|media|Users|run|root)/[^\s:'\"()<>]+",
               "<local-path>", s)
    s = re.sub(r"\b0[0-9]{9,11}\b", "<number>", s)
    s = re.sub(r"\b[a-fA-F0-9]{40,}\b", "<long-hex>", s)
    return "\n".join(s.splitlines()[-20:])[:1600]


def collect(work=WORK):
    from audit_b6q_selinux_inputs import inspect
    from compile_b6q_selinux import compile_policy
    from run_b6q_checkvintf import run_check
    from audit_b6q_vintf_contracts import inspect as inspect_hal_contracts
    from audit_b6q_avb_trust_graph import audit as inspect_avb_graph

    data = {}
    try:
        report = inspect(work)
        data["policy_mapping"] = safe_status(report.get("status"))
        data["mapping_exists"] = bool(report.get("donor_system_compat_mapping_found"))
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        data["policy_mapping"] = "NOT_RUN_INCOMPLETE_INPUT"
        data["mapping_exists"] = False
    try:
        report = compile_policy(work)
        data["secilc"] = safe_status(report.get("status"))
        data["neverallow"] = safe_status(report.get("neverallow_check"))
        data["strict_phase"] = safe_status(report.get("strict_pass_status"))
        data["strict_failure_category"] = safe_status(
            report.get("strict_failure_category")
        )
        inputs = report.get("passes") or {}
        data["secilc_errors"] = scrub_errors(
            (inputs.get("init_equivalent") or {}).get("stderr_tail", "")
            or report.get("reason", ""))
        triage = report.get("neverallow_rule_triage") or {}
        safe = triage.get("public_fields") or {}
        data["neverallow_locations_status"] = safe_status(safe.get("status"))
        data["neverallow_location_count"] = int(
            safe.get("suspected_violation_lines") or 0
        )
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        data["secilc"] = "NOT_RUN_INCOMPLETE_INPUT"
        data["neverallow"] = "NOT_RUN"
        data["strict_phase"] = "NOT_RUN"
        data["strict_failure_category"] = "NOT_RUN"
        data["secilc_errors"] = ""
        data["neverallow_locations_status"] = "NOT_RUN"
        data["neverallow_location_count"] = 0
    try:
        report = run_check(work)
        data["checkvintf"] = safe_status(report.get("status"))
        data["checkvintf_errors"] = scrub_errors(report.get("stderr", ""))
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        data["checkvintf"] = "NOT_RUN_INCOMPLETE_INPUT"
        data["checkvintf_errors"] = ""
    try:
        contract = inspect_hal_contracts(work)
        data["hal_contracts"] = safe_status(contract.get("status"))
        data["hal_required"] = int(contract.get("required_entries", 0))
        data["hal_matched"] = int(contract.get("matched_entries", 0))
        data["hal_candidates"] = len(contract.get("possible_mismatches", []))
        data["hal_unknown_reasons"] = dict(
            contract.get("unsupported_reason_counts") or {}
        )
        data["hal_incomplete_cause_count"] = len(
            contract.get("incomplete_cause_codes") or []
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        data["hal_contracts"] = "NOT_RUN_INCOMPLETE_INPUT"
        data["hal_required"] = 0
        data["hal_matched"] = 0
        data["hal_candidates"] = 0
        data["hal_unknown_reasons"] = {}
        data["hal_incomplete_cause_count"] = 0
    try:
        graph = inspect_avb_graph(
            work, ROOT / "out/b6q/analysis/f741n-bl-vbmeta-chain.json",
            ROOT / "out/b6q/analysis/f741n-stock-boot-chain/vbmeta_system.img",
        )
        data["avb_graph"] = safe_status(graph.get("status"))
        data["avb_root_overlap"] = len(
            (graph.get("trust_graph") or {}).get(
                "modified_partition_signed_descriptor_overlap", []
            )
        )
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        data["avb_graph"] = "NOT_RUN_INCOMPLETE_INPUT"
        data["avb_root_overlap"] = 0
    return data


def markdown_report(result, include_errors=False):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "<!-- DUYKHAIDEX_F741N_STATUS -->",
        "### DuyKhaiDeX F741N — status only",
        "Updated: " + now,
        "",
        "| Check | Status |",
        "| --- | --- |",
        "| F741N vendor / F956N SELinux mapping | " +
            safe_status(result.get("policy_mapping")) + " |",
        "| Mapping file found | " + str(bool(result.get("mapping_exists"))) + " |",
        "| Mixed host SELinux secilc | " + safe_status(result.get("secilc")) + " |",
        "| Strict host neverallow | " + safe_status(result.get("neverallow")) + " |",
        "| Strict compiler pass | " + safe_status(result.get("strict_phase")) + " |",
        "| Strict failure category (no raw errors) | " +
            safe_status(result.get("strict_failure_category")) + " |",
        "| SELinux neverallow rule location scan | " +
            safe_status(result.get("neverallow_locations_status")) + " |",
        "| SELinux neverallow location hints | " +
            str(int(result.get("neverallow_location_count", 0))) + " |",
        "| AOSP host checkvintf | " + safe_status(result.get("checkvintf")) + " |",
        "| F741N required HAL contracts (partial XML audit) | " +
            safe_status(result.get("hal_contracts")) + " |",
        "| HAL contract entries matched | " +
            str(int(result.get("hal_matched", 0))) + "/" +
            str(int(result.get("hal_required", 0))) + " |",
        "| HAL mismatch candidates | " +
            str(int(result.get("hal_candidates", 0))) + " |",
        "| VINTF XML unknown cause categories | " +
            str(int(result.get("hal_incomplete_cause_count", 0))) + " |",
        "| AVB BL signed descriptor overlap | " +
            safe_status(result.get("avb_graph")) + " |",
        "| AVB signed modified partitions count | " +
            str(int(result.get("avb_root_overlap", 0))) + " |",
        "| Rebuilt system verified boot | BLOCKED_UNVERIFIED |",
        "| Odin AP authorized | NO |",
        "",
        "Public sanitized statuses only. Not a boot, AVB or flash safety approval.",
    ]
    # Only allowlisted reason identifiers and integer counts from XML.
    reasons = result.get("hal_unknown_reasons") or {}
    for reason, value in sorted(reasons.items()):
        if safe_status(reason) != "UNKNOWN" and type(value) is int and 0 < value < 10000:
            lines.append("| VINTF unknown " + safe_status(reason) + " | " + str(value) + " |")
    if include_errors:
        for label, key in (("SELinux compiler", "secilc_errors"),
                           ("Host checkvintf", "checkvintf_errors")):
            fragment = result.get(key, "").strip()
            if fragment:
                lines += ["", label + " — redacted error excerpt:", "~~~text",
                          scrub_errors(fragment), "~~~"]
    return "\n".join(lines) + "\n"


def publish_public(body):
    cli = shutil.which("gh")
    if not cli:
        raise RuntimeError("GitHub CLI gh missing. Install and authenticate once.")
    auth = subprocess.run([cli, "auth", "status"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=15, check=False)
    if auth.returncode:
        raise RuntimeError("GitHub CLI needs authentication: gh auth login")
    posted = subprocess.run(
        [cli, "pr", "comment", PR, "--repo", REPO, "--body-file", "-"],
        input=body, text=True, capture_output=True, timeout=45, check=False,
    )
    if posted.returncode:
        raise RuntimeError("Could not post sanitized PR comment: check GitHub permission.")
    return posted.stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-public", action="store_true",
                        help="Consent to post sanitized statuses to a PUBLIC PR")
    parser.add_argument("--include-redacted-errors", action="store_true",
                        help="Also post scrubbed compiler errors publicly; may remain sensitive")
    args = parser.parse_args(argv)
    if args.include_redacted_errors and not args.publish_public:
        parser.error("--include-redacted-errors requires --publish-public")
    sys.path.insert(0, str(ROOT / "scripts"))
    data = collect()
    report = markdown_report(data, args.include_redacted_errors)
    if not args.publish_public:
        print(report)
        print("NOT UPLOADED; use --publish-public for opt-in public reporting.")
        return 0
    try:
        url = publish_public(report)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, "Cannot publish: " + str(error) + "\n")
    print("SANITIZED STATUS PUBLISHED:", url or
          "https://github.com/" + REPO + "/pull/" + PR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
