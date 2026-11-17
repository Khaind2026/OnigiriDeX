"""Unit tests for the safe F741N/F956N filename preflight (no ROM needed)."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from scripts.preflight_f741n import EXPECTED, inventory, list_filenames, main


def samples(model):
    tag = model.replace("SM-", "")
    return [
        f"AP_{EXPECTED[model]['AP']}_{tag}_meta.tar.md5",
        f"BL_{EXPECTED[model]['BL']}_{tag}_meta.tar.md5",
        f"CP_{EXPECTED[model]['CP']}_{tag}_meta.tar.md5",
        f"CSC_OKR_{EXPECTED[model]['CSC']}_{tag}_meta.tar.md5",
    ]


class PreflightTests(unittest.TestCase):
    def test_shared_directory_selects_only_matching_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for filename in samples("SM-F741N") + samples("SM-F956N"):
                (path / filename).touch()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--flip6", str(path), "--fold6", str(path)]), 0)
            f741 = inventory(list_filenames(path), "SM-F741N", path)
            f956 = inventory(list_filenames(path), "SM-F956N", path)
            self.assertFalse(f741["errors"])
            self.assertFalse(f956["errors"])
            self.assertTrue(all("F741N" in f for files in f741["packages"].values() for f in files))
            self.assertTrue(all("F956N" in f for files in f956["packages"].values() for f in files))

    def test_wrong_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for filename in samples("SM-F741N"):
                (path / filename).touch()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--flip6", str(path), "--fold6", str(path)]), 2)

    def test_unexpected_build_is_rejected(self):
        filenames = samples("SM-F956N")
        filenames[0] = filenames[0].replace("F956NKSS2BYGB", "F956NKSS2BYZZ")
        result = inventory(filenames, "SM-F956N", Path("/example"))
        self.assertTrue(any("expected F956NKSS2BYGB" in e for e in result["errors"]))

    def test_duplicate_archive_is_rejected(self):
        filenames = samples("SM-F741N")
        filenames.append(filenames[0].replace("_meta.", "_again."))
        self.assertTrue(inventory(filenames, "SM-F741N", Path("/example"))["errors"])


if __name__ == "__main__":
    unittest.main()
