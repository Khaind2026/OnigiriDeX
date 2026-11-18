"""Synthetic offline tests for host split SELinux compilation of F741N/F956N."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compile_b6q_selinux import policy_inputs, compile_policy, classify_strict_failure


class SeLinuxCompileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / ".b6q-prepared").write_text("ready\n")
        (self.root / "port-origin.json").write_text(json.dumps({
            "target": "SM-F741N", "donor": "SM-F956N",
        }))
        files = (
            "system/system/etc/selinux/plat_sepolicy.cil",
            "system/system/etc/selinux/mapping/34.0.cil",
            "system_ext/etc/selinux/system_ext_sepolicy.cil",
            "product/etc/selinux/product_sepolicy.cil",
            "vendor/etc/selinux/plat_pub_versioned.cil",
            "vendor/etc/selinux/vendor_sepolicy.cil",
            "vendor/etc/selinux/plat_sepolicy_vers.txt",
            "system/system/etc/selinux/plat_file_contexts",
            "vendor/etc/selinux/vendor_file_contexts",
        )
        for name in files:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("34.0\n" if name.endswith("vers.txt") else "(type example)\n")
        for part in ("system", "product", "system_ext", "vendor",
                     "odm", "vendor_dlkm", "system_dlkm"):
            f = self.root / "configs" / ("file_context-" + part)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("dummy\n")

    def test_uses_required_vendor_pub_cil_and_versioned_mapping(self):
        vers, files = policy_inputs(self.root)
        self.assertEqual(vers, "34.0")
        names = [label for label, _, _ in files]
        self.assertIn("vendor/plat_pub_versioned.cil", names)
        self.assertIn("system/mapping/34.0.cil", names)
        self.assertNotIn("odm/odm_sepolicy.cil", names)

    @mock.patch("compile_b6q_selinux.subprocess.run")
    def test_two_compile_passes_both_still_not_bootable(self, execute):
        execute.return_value = subprocess.CompletedProcess([], 0, "", "")
        r = compile_policy(self.root, compiler="/mock/secilc")
        self.assertEqual(r["status"], "HOST_SELINUX_COMPILE_PASSED_RUNTIME_UNVERIFIED")
        self.assertEqual(r["neverallow_check"], "PASSED_HOST_ONLY")
        self.assertEqual(execute.call_count, 2)
        args1 = execute.call_args_list[0].args[0]
        args2 = execute.call_args_list[1].args[0]
        self.assertIn("-N", args1)
        self.assertNotIn("-N", args2)
        self.assertIn("-c", args1)
        self.assertIn("30", args1)
        self.assertFalse(r["bootable"])
        self.assertFalse(r["flashable"])

    @mock.patch("compile_b6q_selinux.subprocess.run")
    def test_init_pass_but_strict_neverallow_failure_is_classified(self, execute):
        execute.side_effect = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 1, "",
                                        "libsepol: neverallow check failed"),
        ]
        r = compile_policy(self.root, compiler="/mock/secilc")
        self.assertEqual(r["status"], "HOST_SELINUX_COMPILE_PASSED_RUNTIME_UNVERIFIED")
        self.assertEqual(r["strict_pass_status"], "FAILED")
        self.assertEqual(r["neverallow_check"], "FAILED_HOST_ONLY")
        self.assertEqual(r["strict_failure_category"], "NEVERALLOW_VIOLATION_DETECTED")
        self.assertFalse(r["flashable"])

    def test_strict_error_categories_do_not_emit_raw_compiler_log(self):
        self.assertEqual(
            classify_strict_failure({
                "status": "FAILED",
                "stderr_tail": "/home/private/abc.cil: unknown type secretname",
            }), "UNRESOLVED_POLICY_SYMBOL",
        )
        self.assertEqual(
            classify_strict_failure({
                "status": "FAILED", "stderr_tail": "syntax error near line 42",
            }), "CIL_SYNTAX_ERROR",
        )
        self.assertEqual(
            classify_strict_failure({
                "status": "FAILED", "stderr_tail": "/home/private/policy: error",
            }), "OTHER_STRICT_COMPILATION_FAILURE",
        )
        self.assertEqual(classify_strict_failure({
            "status": "ERROR", "reason": "TimeoutExpired",
        }), "COMPILER_TIMEOUT")

    @mock.patch("compile_b6q_selinux.subprocess.run")
    def test_compile_failure_remains_blocker(self, execute):
        execute.return_value = subprocess.CompletedProcess([], 1, "", "invalid CIL")
        r = compile_policy(self.root, compiler="/mock/secilc")
        self.assertEqual(r["status"], "HOST_SELINUX_COMPILE_FAILED")
        self.assertEqual(r["passes"]["init_equivalent"]["stderr_tail"], "invalid CIL")
        self.assertFalse(r["flashable"])

    def test_missing_vendor_public_cil_is_not_success(self):
        (self.root / "vendor/etc/selinux/plat_pub_versioned.cil").unlink()
        r = compile_policy(self.root, compiler="/mock/secilc")
        self.assertEqual(r["status"], "NOT_RUN_INCOMPLETE_POLICY_INPUTS")
        self.assertIn("plat_pub_versioned.cil", r["reason"])

    def test_missing_mapping_not_success(self):
        (self.root / "system/system/etc/selinux/mapping/34.0.cil").unlink()
        r = compile_policy(self.root, compiler="/mock/secilc")
        self.assertEqual(r["status"], "NOT_RUN_INCOMPLETE_POLICY_INPUTS")
        self.assertFalse(r["flashable"])

    @mock.patch("compile_b6q_selinux.shutil.which", return_value=None)
    def test_missing_compiler_is_not_success(self, _):
        r = compile_policy(self.root)
        self.assertEqual(r["status"], "NOT_RUN_SECILC_MISSING")
        self.assertFalse(r["flashable"])


if __name__ == "__main__":
    unittest.main()
