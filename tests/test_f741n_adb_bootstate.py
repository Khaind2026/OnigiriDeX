"""Synthetic tests for privacy-preserving F741N ADB boot-state readout."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inspect_b6q_device_bootstate import inspect, PROPERTIES


def success(stdout):
    return subprocess.CompletedProcess(["adb"], 0, stdout, "")


class AdbBootstateTests(unittest.TestCase):
    @mock.patch("inspect_b6q_device_bootstate.shutil.which", return_value=None)
    def test_no_adb_is_not_a_pass(self, _):
        record = inspect()
        self.assertEqual(record["status"], "NOT_RUN_ADB_UNAVAILABLE")
        self.assertFalse(record["flashable"])

    @mock.patch("inspect_b6q_device_bootstate.subprocess.run")
    def test_unlocked_device_property_not_crypto_attestation(self, cmd):
        values = {key: "" for key in PROPERTIES}
        values["ro.product.model"] = "SM-F741N"
        values["ro.product.vendor.model"] = "SM-F741N"
        values["ro.boot.vbmeta.device_state"] = "unlocked"
        cmd.side_effect = [
            success("List of devices attached\nTEST_DEVICE_SERIAL\tdevice\n"),
            *(success(values[key] + "\n") for key in PROPERTIES),
        ]
        result = inspect("/mock/adb")
        self.assertEqual(result["status"], "DEVICE_REPORTS_UNLOCKED_NOT_ATTESTED")
        self.assertFalse(result["trusted_attestation"])
        self.assertFalse(result["flashable"])
        self.assertNotIn("TEST_DEVICE_SERIAL", json.dumps(result))

    @mock.patch("inspect_b6q_device_bootstate.subprocess.run")
    def test_locked_device_blocks_custom_rom(self, cmd):
        values = {key: "" for key in PROPERTIES}
        values["ro.product.vendor.model"] = "SM-F741N"
        values["ro.boot.vbmeta.device_state"] = "locked"
        cmd.side_effect = [
            success("List of devices attached\nTEST_SERIAL\tdevice\n"),
            *(success(values[key] + "\n") for key in PROPERTIES),
        ]
        result = inspect("/mock/adb")
        self.assertEqual(result["status"], "DEVICE_REPORTS_LOCKED_CUSTOM_ROM_BLOCKED")
        self.assertFalse(result["flashable"])

    @mock.patch("inspect_b6q_device_bootstate.subprocess.run")
    def test_multiple_devices_are_refused_without_identifiers(self, cmd):
        cmd.return_value = success(
            "List of devices attached\nSERIAL1\tdevice\nSERIAL2\tdevice\n"
        )
        result = inspect("/mock/adb")
        self.assertEqual(result["status"],
                         "NOT_RUN_EXACTLY_ONE_AUTHORIZED_DEVICE_REQUIRED")
        self.assertNotIn("SERIAL", json.dumps(result))

    @mock.patch("inspect_b6q_device_bootstate.subprocess.run")
    def test_non_target_is_ignored(self, cmd):
        values = {key: "" for key in PROPERTIES}
        values["ro.product.vendor.model"] = "SM-F956N"
        cmd.side_effect = [
            success("List of devices attached\nTEST_SERIAL\tdevice\n"),
            *(success(values[key] + "\n") for key in PROPERTIES),
        ]
        result = inspect("/mock/adb")
        self.assertEqual(result["status"], "NOT_RUN_NON_F741N_DEVICE")
        self.assertNotIn("properties", result)
        self.assertFalse(result["flashable"])


if __name__ == "__main__":
    unittest.main()
