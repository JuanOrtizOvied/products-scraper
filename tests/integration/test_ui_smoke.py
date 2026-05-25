def test_ui_app_syntactically_valid():
    import ast
    from pathlib import Path

    app_path = Path(__file__).resolve().parents[2] / "src" / "scraper" / "ui" / "app.py"
    assert app_path.exists()
    ast.parse(app_path.read_text(encoding="utf-8"))


def test_ui_pages_syntactically_valid():
    import ast
    from pathlib import Path

    pages_dir = Path(__file__).resolve().parents[2] / "src" / "scraper" / "ui" / "pages"
    for page_file in pages_dir.glob("*.py"):
        if page_file.name == "__init__.py":
            continue
        ast.parse(page_file.read_text(encoding="utf-8"))
