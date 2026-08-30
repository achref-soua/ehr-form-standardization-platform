"""Safe CDA section extraction for the bounded narrative path."""

from __future__ import annotations

from dataclasses import dataclass

from defusedxml import ElementTree

from ehrfs.domain.errors import DomainError


@dataclass(frozen=True, slots=True)
class CdaSection:
    title: str
    text: str


def extract_cda_sections(payload: bytes) -> tuple[CdaSection, ...]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise DomainError("INVALID_CDA_XML", "CDA document is not safe, well-formed XML") from error
    sections: list[CdaSection] = []
    for section in root.findall(".//{*}section"):
        title = " ".join("".join(section.findtext("{*}title", default="")).split())
        text_element = section.find("{*}text")
        text = "" if text_element is None else " ".join("".join(text_element.itertext()).split())
        if title or text:
            sections.append(CdaSection(title=title or "Untitled section", text=text))
    return tuple(sections)
