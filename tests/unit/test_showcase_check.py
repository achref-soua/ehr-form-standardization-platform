from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from scripts import showcase_check


class _ReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _ready_server() -> tuple[ThreadingHTTPServer, Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReadyHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_check_endpoint_reports_ready_and_failure() -> None:
    server, thread = _ready_server()
    try:
        endpoint = showcase_check.Endpoint("Test", server.server_port, "/health", "Test")
        ready = showcase_check.check_endpoint(endpoint, 1.0)
        assert ready.ready
        assert ready.status == 200
        assert ready.error is None
        assert ready.url == f"http://localhost:{server.server_port}/health"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    failed = showcase_check.check_endpoint(
        showcase_check.Endpoint("Missing", server.server_port, "/health", "Test"), 0.1
    )
    assert not failed.ready
    assert failed.status is None
    assert failed.error


def test_main_emits_machine_readable_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server, thread = _ready_server()
    monkeypatch.setattr(
        showcase_check,
        "ENDPOINTS",
        (showcase_check.Endpoint("Test", server.server_port, "/", "Test"),),
    )
    try:
        assert showcase_check.main(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ready"] is True
        assert report["services"][0]["name"] == "Test"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_human_report_keeps_readiness_boundary_visible() -> None:
    report = showcase_check._render_human(
        (showcase_check.CheckResult("API", "http://localhost:8000", False, 503, "down"),)
    )
    assert "[FAILED]" in report
    assert "0/1 services ready" in report
