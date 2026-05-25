import subprocess
import sys


def test_calibrate_pipeline_dry_run():
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.calibrate_pipeline", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Calibración pipeline" in result.stdout or "dry-run" in result.stdout.lower()


def test_calibrate_pipeline_dry_run_with_exclude_clase():
    """--exclude-clase accepted without error in dry-run mode."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scraper.scripts.calibrate_pipeline",
            "--dry-run",
            "--exclude-clase",
            "Club deals,Inmobiliario Directo",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_calibrate_pipeline_dry_run_with_only_nombres():
    """--only-nombres accepted without error in dry-run mode."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scraper.scripts.calibrate_pipeline",
            "--dry-run",
            "--only-nombres",
            "Credicorp Crecimiento",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_calibrate_pipeline_mutually_exclusive_flags_not_enforced():
    """If both --exclude-clase and --only-nombres are passed, --only-nombres wins.
    No error (they're additive flags, not mutex)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scraper.scripts.calibrate_pipeline",
            "--dry-run",
            "--only-nombres",
            "X",
            "--exclude-clase",
            "Club deals",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
