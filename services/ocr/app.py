"""Local-only PaddleOCR HTTP boundary with bounded inputs and evidence boxes."""

from __future__ import annotations

import hashlib
import os
import threading
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from time import perf_counter
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

MAXIMUM_BYTES = int(os.getenv("EHRFS_OCR_MAX_BYTES", str(15 * 1024 * 1024)))
MAXIMUM_PIXELS = int(os.getenv("EHRFS_OCR_MAX_PIXELS", "40000000"))
DEVICE: Literal["cpu", "gpu"] = "gpu" if os.getenv("EHRFS_OCR_DEVICE") == "gpu" else "cpu"
LANGUAGE = os.getenv("EHRFS_OCR_LANGUAGE", "fr")
MODEL_FAMILY = os.getenv("EHRFS_OCR_MODEL", "PP-OCRv5")
MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/tiff"})
BOX_COORDINATES = 4
OCR_REQUESTS = Counter(
    "ehrfs_ocr_requests_total", "Local OCR requests by device and outcome", ("device", "outcome")
)
OCR_DURATION = Histogram(
    "ehrfs_ocr_duration_seconds", "Local OCR inference duration", ("device", "model")
)
OCR_CONFIDENCE = Histogram(
    "ehrfs_ocr_span_confidence",
    "Local OCR evidence span confidence",
    ("device",),
    buckets=(0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99, 1.0),
)


class OcrSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    confidence: float = Field(ge=0, le=1)
    bounding_box: tuple[float, float, float, float]


class OcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    spans: tuple[OcrSpan, ...]
    model_version: str


class OcrResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: tuple[OcrPage, ...]
    device: Literal["cpu", "gpu"]
    elapsed_ms: float = Field(ge=0)
    model_version: str
    image_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaddleEngine:
    """Lazily loads model weights so health checks never trigger downloads."""

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def _load(self) -> Any:
        if self._pipeline is None:
            with self._lock:
                if self._pipeline is None:
                    from paddleocr import PaddleOCR  # noqa: PLC0415 -- preserve lazy model loading

                    self._pipeline = PaddleOCR(
                        lang=LANGUAGE,
                        ocr_version=MODEL_FAMILY,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        device="gpu:0" if DEVICE == "gpu" else "cpu",
                    )
        return self._pipeline

    def predict(self, image: Image.Image) -> tuple[OcrSpan, ...]:
        results = self._load().predict(np.asarray(image.convert("RGB")))
        spans: list[OcrSpan] = []
        for result in results:
            payload = result.json
            if callable(payload):
                payload = payload()
            values = payload.get("res", payload)
            texts = values.get("rec_texts", ())
            scores = values.get("rec_scores", ())
            boxes = values.get("rec_boxes", ())
            for text, score, box in zip(texts, scores, boxes, strict=False):
                coordinates = tuple(float(value) for value in box)
                if len(coordinates) != BOX_COORDINATES:
                    continue
                spans.append(
                    OcrSpan(
                        text=str(text),
                        confidence=float(score),
                        bounding_box=coordinates,
                    )
                )
        return tuple(spans)


engine = PaddleEngine()
app = FastAPI(
    title="EHRFS local OCR",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _model_version() -> str:
    paddleocr_version = version("paddleocr")
    try:
        paddle_version = version("paddlepaddle")
    except PackageNotFoundError:
        paddle_version = version("paddlepaddle-gpu")
    return f"{MODEL_FAMILY}/{LANGUAGE}@paddleocr-{paddleocr_version}/paddle-{paddle_version}"


def _decode_image(content: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(content))
        image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise HTTPException(
            status_code=422, detail="The upload is not a valid bounded image"
        ) from error
    if image.width * image.height > MAXIMUM_PIXELS:
        raise HTTPException(status_code=413, detail="The decoded image exceeds the pixel limit")
    return image


@app.get("/healthz")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "device": DEVICE, "model_loaded": engine.loaded}


@app.get("/readyz")
def readiness() -> dict[str, str]:
    return {"status": "ready", "loading": "lazy"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/ocr", response_model=OcrResponse)
async def extract(
    upload: Annotated[UploadFile, File()],
    content_checksum: Annotated[str | None, Header(alias="X-Content-SHA256")] = None,
) -> OcrResponse:
    media_type = upload.content_type or "application/octet-stream"
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported OCR media type")
    content = await upload.read(MAXIMUM_BYTES + 1)
    if not content or len(content) > MAXIMUM_BYTES:
        raise HTTPException(status_code=413, detail="The OCR upload is empty or too large")
    checksum = hashlib.sha256(content).hexdigest()
    if content_checksum is not None and content_checksum != checksum:
        raise HTTPException(status_code=409, detail="Content checksum mismatch")
    image = _decode_image(content)
    started = perf_counter()
    spans = engine.predict(image)
    elapsed_ms = (perf_counter() - started) * 1000
    model_version = _model_version()
    OCR_REQUESTS.labels(DEVICE, "succeeded").inc()
    OCR_DURATION.labels(DEVICE, MODEL_FAMILY).observe(elapsed_ms / 1000)
    for span in spans:
        OCR_CONFIDENCE.labels(DEVICE).observe(span.confidence)
    return OcrResponse(
        pages=(
            OcrPage(
                page=1,
                width=image.width,
                height=image.height,
                spans=spans,
                model_version=model_version,
            ),
        ),
        device=DEVICE,
        elapsed_ms=elapsed_ms,
        model_version=model_version,
        image_checksum_sha256=checksum,
    )
