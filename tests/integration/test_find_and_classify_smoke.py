import subprocess
import sys


def test_find_and_classify_requires_nombre():
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.find_and_classify"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0


def test_find_and_classify_dry_run():
    """--dry-run should not call any API — short-circuit and print a message."""
    result = subprocess.run(
        [
            sys.executable, "-m", "scraper.scripts.find_and_classify",
            "Credicorp Crecimiento", "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "dry-run" in result.stdout.lower()


def test_find_and_classify_url_and_pdf_mutually_exclusive():
    """argparse group must reject both --url and --pdf at once."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-m", "scraper.scripts.find_and_classify",
            "X", "--url", "https://a.com", "--pdf", "x.pdf",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0


def test_find_and_classify_dry_run_with_url_describes_source():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-m", "scraper.scripts.find_and_classify",
            "Fondo X", "--url", "https://alianza.com.co/fondo/y", "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "url=https://alianza.com.co/fondo/y" in result.stdout
