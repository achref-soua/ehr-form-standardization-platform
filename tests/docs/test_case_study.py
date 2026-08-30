"""Public case-study document contract tests."""

from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "docs/case-study/case-study.fr.html"
PDF = ROOT / "docs/case-study/epiconcept-case-study.fr.pdf"


def test_case_study_is_french_and_exactly_eight_pages() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert '<html lang="fr">' in source
    assert source.count('class="page"') == 8
    assert "compensation" not in source.casefold()
    assert len(PdfReader(PDF).pages) == 8


def test_case_study_uses_prerendered_diagrams_and_brand_asset() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert '<pre class="mermaid"' not in source
    assert source.count("diagrams/generated/") == 5
    assert source.count("../assets/brand/epiconcept-logo.png") == 8
