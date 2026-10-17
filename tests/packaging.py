#!/usr/bin/env python3
"""Verify bundled resources and the standalone launcher contract."""
from importlib.resources import files
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
launcher = ROOT / "skills/linkcontext/linkcontext"
assert files("linkcontext_client").joinpath("schema.json").read_bytes() == (ROOT / "skills/linkcontext/references/schema.json").read_bytes()
assert re.search(r"linkcontext\.git@[0-9a-f]{40}", launcher.read_text())
assert launcher.stat().st_mode & 0o111
with tempfile.TemporaryDirectory(prefix="linkcontext-launcher-") as directory:
    copied = Path(directory) / "linkcontext"
    shutil.copyfile(launcher, copied)
    result = subprocess.run([sys.executable, str(copied), "--help"], cwd=directory, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "linkcontext" in result.stdout
print("PASS: packaged schema and copied full-name launcher")
