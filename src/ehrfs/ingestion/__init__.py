"""Typed source adapters for the bounded demonstration."""

from ehrfs.ingestion.fhir import FhirR4Adapter
from ehrfs.ingestion.structured import JsonFormAdapter, XmlFormAdapter
from ehrfs.ingestion.tabular import TabularAnswer, TabularFormAdapter

__all__ = [
    "FhirR4Adapter",
    "JsonFormAdapter",
    "TabularAnswer",
    "TabularFormAdapter",
    "XmlFormAdapter",
]
