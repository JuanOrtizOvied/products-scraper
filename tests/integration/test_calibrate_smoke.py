import subprocess
import sys


def test_calibrate_dry_run_completes():
    """Dry-run mode should execute pipeline without API, producing 100% accuracy
    (because dry-run feeds ground truth as prediction).

    encoding="utf-8" mirrors the pattern used in test_classify_one_smoke.py:
    the CLI reconfigures its stdout to utf-8 to handle non-ASCII chars like
    "Calibración", "█", "✓", "✗" and accented product names, so the parent
    must decode as utf-8 too. Without this, cp1252 on Windows mangles bytes
    and the "Calibración v1" assertion below fails.
    """
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.calibrate", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Calibración v1" in result.stdout
    assert "100.0%" in result.stdout  # all attrs 100% in dry-run
