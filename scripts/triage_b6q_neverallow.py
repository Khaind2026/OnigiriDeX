#!/usr/bin/env python3
"""Read-only SELinux neverallow failure locator for mixed F956N/F741N CIL.

The compiler output is already obtained by compile_b6q_selinux.py.
Keep any raw source excerpts in the LOCAL report only; public status outputs
ONLY allowlisted result codes and counts. Never remove a neverallow rule,
change SELinux enforcement or patch firmware to pass checks.
"""
import hashlib
import re

MAX_LOCAL_VIOLATIONS = 50
MAX_LOCAL_LINES = 300
MAX_LINE_BYTES = 500

# secilc/libsepol versions vary in their failure wording. Unknown syntax
# remains UNKNOWN rather than inventing a rule/line location.
LINE_HINT = re.compile(
    r"(?i)\b(?:line|lineno)\s+(\d{1,9})\b|:(\d{1,9})(?:\D|$)"
)
ALLOW_CIL = re.compile(
    r"(?m)\(\s*(allow|allowx|allowxperm)\s+"
    r"([A-Za-z_.$0-9-]+)\s+([A-Za-z_.$0-9-]+)\s+"
    r"\(\s*([A-Za-z0-9_.$-]+)"
)
SOURCE_KIND = re.compile(r"(?i)(?:^|/)(system_ext|system|product|vendor|odm)(?:/|$)")


def origin_kind(line):
    names = SOURCE_KIND.findall(line)
    return names[0].lower() if names else "UNKNOWN_SOURCE"


def analyze(compile_report):
    phases = compile_report.get("passes") if isinstance(compile_report, dict) else {}
    strict = phases.get("strict_neverallow") if isinstance(phases, dict) else {}
    if not isinstance(strict, dict):
        strict = {}
    state = strict.get("status", "NOT_RUN")
    output = str(strict.get("stderr_tail", "")) + "\n" + str(strict.get("stdout_tail", ""))
    # Never summarize the init-equivalent -N pass as a neverallow result.
    lines = output.splitlines()[-MAX_LOCAL_LINES:]
    suspicious = []
    allow_classes = {}
    source_counts = {}
    for index, line in enumerate(lines):
        if not re.search(r"(?i)\bneverallow\b", line):
            continue
        # Avoid falsely treating a single summary as multiple separate rules.
        if re.search(r"(?i)^\s*(?:\d+\s+neverallow failures|neverallow failures occurred)", line):
            continue
        context = "\n".join(lines[max(0, index - 1):min(len(lines), index + 3)])
        match = LINE_HINT.search(line)
        # Local report stores a bounded diagnostic excerpt. It is NEVER
        # published in a PR comment and will not contain full policy files.
        kind = origin_kind(context)
        source_counts[kind] = source_counts.get(kind, 0) + 1
        rule = {
            "local_excerpt": context[:MAX_LINE_BYTES],
            "first_line_number_hint": int(next((x for x in match.groups() if x), "0"))
                if match else None,
            "origin_partition_hint": kind,
            "line_fingerprint": hashlib.sha256(line.strip().encode()).hexdigest()[:16],
        }
        suspicious.append(rule)
        if len(suspicious) >= MAX_LOCAL_VIOLATIONS:
            break
    for found in ALLOW_CIL.finditer(output):
        klass = found.group(4)
        if re.fullmatch(r"[A-Za-z0-9_.$-]{1,64}", klass):
            allow_classes[klass] = allow_classes.get(klass, 0) + 1
    if state == "COMPILED":
        status = "HOST_STRICT_POLICY_COMPILED"
    elif state != "FAILED":
        status = "NOT_RUN_OR_COMPILER_ERROR"
    elif suspicious:
        status = "NEVERALLOW_RULE_LOCATIONS_IDENTIFIED_PARTIALLY"
    elif "neverallow" in output.lower():
        status = "NEVERALLOW_VIOLATIONS_PRESENT_UNPARSED_DIAGNOSTIC"
    else:
        status = "STRICT_FAILED_WITHOUT_NEVERALLOW_RULE_LOCATIONS"
    return {
        "status": status,
        "strict_compiler_status": state,
        "suspected_violation_lines": len(suspicious),
        "source_partition_hint_counts": dict(sorted(source_counts.items())),
        "allow_statement_class_counts": dict(sorted(allow_classes.items())),
        "local_rule_evidence": suspicious,
        "local_evidence_may_contain_vendor_policy": True,
        "public_fields": {
            "status": status,
            "suspected_violation_lines": len(suspicious),
            "sources_identified": len(source_counts),
            "affected_class_types": len(allow_classes),
        },
        "flashable": False,
        "warning": "A line hint alone cannot identify a precise allow/neverallow pair; full local diagnostic evidence is needed. Do not disable SELinux to pass.",
    }
