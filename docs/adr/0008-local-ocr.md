# ADR 0008: Local, isolated OCR

Status: Accepted — 2026-08-29

## Decision

Extract native PDF/CDA text first and invoke OCR only for relevant image-only evidence. PaddleOCR
runs in separate CPU/GPU containers with their own locks, persistent model cache, bounded input,
and no hosted inference. Core shows committed golden evidence and starts without model downloads.

## Consequences

OCR dependency and CUDA constraints cannot destabilize the Python 3.12 application. Live inference
is slower on first use, model provenance must be recorded, and low confidence causes abstention.
