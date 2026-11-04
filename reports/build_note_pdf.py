"""Render reports/client_note.md to reports/client_note.pdf (A4, two pages).

Usage: python reports/build_note_pdf.py
Needs: pip install markdown playwright && playwright install chromium
"""
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

CSS = """
@page { size: A4; margin: 13mm 15mm 12mm 15mm; }
body { font-family: "Inter", "Segoe UI", Helvetica, Arial, sans-serif; color: #1b1b1a;
       font-size: 9.1pt; line-height: 1.38; background: #fff; }
h1 { font-size: 15.5pt; margin: 0 0 4px; color: #0b0b0b; line-height: 1.2; }
h1 + p { color: #52514e; font-size: 8.3pt; margin: 0 0 8px; padding-bottom: 7px; border-bottom: 1px solid #d9d8d2; }
h2 { font-size: 10.8pt; margin: 10px 0 4px; color: #1c5cab; }
p { margin: 3px 0 5px; }
ul, ol { margin: 3px 0 6px; padding-left: 17px; }
li { margin: 2px 0; }
img { width: 100%; margin: 3px 0 2px; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 7px; font-size: 8.4pt; }
th, td { border-bottom: 1px solid #e6e5e1; padding: 3px 6px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { background: #f3f2ef; font-weight: 600; }
h2:first-of-type + ul { background: #f3f7fd; border-left: 3px solid #2a78d6; padding: 6px 10px 6px 24px; }
"""


def build() -> Path:
    md_text = (HERE / "client_note.md").read_text(encoding="utf-8")
    body = markdown.markdown(md_text, extensions=["tables"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    html_path = HERE / "_client_note.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = HERE / "client_note.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri())
        page.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    html_path.unlink()
    return pdf_path


if __name__ == "__main__":
    print(build())
