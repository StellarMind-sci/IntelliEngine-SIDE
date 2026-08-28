from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "verify_governance.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_governance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VerifyGovernanceTests(unittest.TestCase):
    def test_accepts_core_governance_without_empty_product_modules_or_skill_catalog(self):
        verifier = load_verifier()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in verifier.REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            original_root = verifier.ROOT
            verifier.ROOT = root
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = verifier.main()
            finally:
                verifier.ROOT = original_root

        self.assertEqual(result, 0)
