"""Validate and normalize the reproducible eight-page French case study."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs/case-study/case-study.fr.html"
PDF = ROOT / "docs/case-study/ehr-form-standardization-case-study.fr.pdf"
EXPECTED_PAGES = 8
MISSING_DOCUMENT_MESSAGE = "Generate the case study before validation"
HTML_PAGE_COUNT_MESSAGE = "The semantic HTML must contain exactly eight pages"
PDF_PAGE_COUNT_MESSAGE = "Expected {expected} PDF pages, found {actual}"
NORMALIZATION_MESSAGE = "Normalization changed the case-study page count"
FIXED_METADATA = {
    "/Title": "Exploitation des formulaires DPI personnalisés",
    "/Author": "Achref Soua",
    "/Subject": "Architecture déterministe de standardisation des formulaires DPI",
    "/Creator": "EHR Form Standardization Platform",
    "/Producer": "Chromium and pypdf",
    "/CreationDate": "D:20260829000000+02'00'",
    "/ModDate": "D:20260829000000+02'00'",
}


def normalize_and_validate() -> None:
    if not HTML.is_file() or not PDF.is_file():
        raise RuntimeError(MISSING_DOCUMENT_MESSAGE)
    source = HTML.read_text(encoding="utf-8")
    if source.count('class="page"') != EXPECTED_PAGES:
        raise RuntimeError(HTML_PAGE_COUNT_MESSAGE)
    reader = PdfReader(PDF)
    if len(reader.pages) != EXPECTED_PAGES:
        raise RuntimeError(
            PDF_PAGE_COUNT_MESSAGE.format(expected=EXPECTED_PAGES, actual=len(reader.pages))
        )
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(FIXED_METADATA)
    with NamedTemporaryFile(dir=PDF.parent, suffix=".pdf", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        writer.write(temporary)
    temporary_path.replace(PDF)
    PDF.chmod(0o644)
    normalized = PdfReader(PDF)
    if len(normalized.pages) != EXPECTED_PAGES:
        raise RuntimeError(NORMALIZATION_MESSAGE)


def main() -> int:
    normalize_and_validate()
    print(f"case study validated: {EXPECTED_PAGES} A4 landscape pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
