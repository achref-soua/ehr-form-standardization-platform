"""Check every user-facing service required for the interview showcase."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from http.client import HTTPConnection
from time import monotonic, sleep


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    port: int
    path: str
    label: str

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}{self.path}"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    url: str
    ready: bool
    status: int | None
    error: str | None


ENDPOINTS = (
    Endpoint("Web application", 3000, "/", "Command center"),
    Endpoint("FastAPI", 8000, "/api/v1/health/ready", "API and OpenAPI"),
    Endpoint("Local OCR", 8081, "/healthz", "CPU OCR boundary"),
    Endpoint("Airflow", 8088, "/api/v2/monitor/health", "Optional scheduler"),
    Endpoint("Grafana", 3001, "/api/health", "Dashboards"),
    Endpoint("Prometheus", 9090, "/-/ready", "Metrics"),
    Endpoint("MinIO", 9000, "/minio/health/ready", "Object storage"),
    Endpoint("OpenTelemetry", 13133, "/", "Telemetry collector"),
)
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX_EXCLUSIVE = 300


def check_endpoint(endpoint: Endpoint, timeout: float) -> CheckResult:
    connection = HTTPConnection("127.0.0.1", endpoint.port, timeout=timeout)
    try:
        connection.request("GET", endpoint.path, headers={"User-Agent": "ehrfs-showcase-check/1"})
        response = connection.getresponse()
        response.read()
        ready = HTTP_SUCCESS_MIN <= response.status < HTTP_SUCCESS_MAX_EXCLUSIVE
        return CheckResult(
            name=endpoint.name,
            url=endpoint.url,
            ready=ready,
            status=response.status,
            error=None if ready else f"unexpected HTTP status {response.status}",
        )
    except (OSError, TimeoutError) as exc:
        return CheckResult(
            name=endpoint.name,
            url=endpoint.url,
            ready=False,
            status=None,
            error=str(exc),
        )
    finally:
        connection.close()


def wait_for_endpoints(
    endpoints: Sequence[Endpoint], *, wait_seconds: float, request_timeout: float
) -> tuple[CheckResult, ...]:
    deadline = monotonic() + wait_seconds
    while True:
        results = tuple(check_endpoint(endpoint, request_timeout) for endpoint in endpoints)
        if all(result.ready for result in results) or monotonic() >= deadline:
            return results
        sleep(min(1.0, max(0.0, deadline - monotonic())))


def _render_human(results: Sequence[CheckResult]) -> str:
    lines = ["EHRFS interview showcase"]
    for result in results:
        marker = "READY" if result.ready else "FAILED"
        suffix = f"HTTP {result.status}" if result.status is not None else result.error
        lines.append(f"[{marker:6}] {result.name:<14} {result.url} ({suffix})")
    ready_count = sum(result.ready for result in results)
    lines.extend(
        (
            "",
            f"Result: {ready_count}/{len(results)} services ready.",
            "Live release data: http://localhost:3000",
            "API contract:      http://localhost:8000/docs",
            "Operational view:  http://localhost:3001",
        )
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    parser.add_argument("--request-timeout", type=float, default=3.0)
    arguments = parser.parse_args(argv)
    if arguments.wait_seconds < 0 or arguments.request_timeout <= 0:
        parser.error("wait seconds must be non-negative and request timeout must be positive")
    results = wait_for_endpoints(
        ENDPOINTS,
        wait_seconds=arguments.wait_seconds,
        request_timeout=arguments.request_timeout,
    )
    if arguments.json:
        print(
            json.dumps(
                {
                    "ready": all(result.ready for result in results),
                    "services": [asdict(result) for result in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_render_human(results))
    return 0 if all(result.ready for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
