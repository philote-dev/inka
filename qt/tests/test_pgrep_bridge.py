# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Contract tests for the L5 pgrep JSON bridge handlers (Channel B).

The three L5.5 handlers (``pgrep_performance_score``, ``pgrep_readiness_score``,
``pgrep_calibration``) are thin ``_json(...)`` wrappers over the pure-Python
engine. These tests pin the contract the web surfaces rely on: each handler is
registered, is reachable at the camelCased endpoint the frontend calls, and
returns JSON-decodable bytes of the expected shape. They run against a fresh
empty collection, so they also demonstrate the honest n=1 abstain state (empty
attempt log -> Performance and Readiness abstain, while Calibration still ships
its embedded evidence).
"""

from __future__ import annotations

import json
import os
import tempfile
import types

import pytest

import aqt
from anki.collection import Collection
from anki.errors import NetworkError, SyncError, SyncErrorKind
from aqt import mediasrv, pgrep, pgrep_operation
from aqt.pgrep_operation import OperationController, ProductSyncUi


@pytest.fixture
def col():
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    collection = Collection(path)
    try:
        yield collection
    finally:
        collection.close()


@pytest.fixture
def bridge(col, monkeypatch):
    """Point the handlers at a real empty collection with an empty JSON body."""
    monkeypatch.setattr(aqt, "mw", types.SimpleNamespace(col=col), raising=False)
    # The handlers that read args (_args) use flask's request.data; a request
    # context with an empty body makes _args() return {}.
    with mediasrv.app.test_request_context(data=b"{}"):
        yield


# --- registration + naming ---------------------------------------------------


def test_new_handlers_are_registered():
    for handler in (
        pgrep.pgrep_performance_score,
        pgrep.pgrep_readiness_score,
        pgrep.pgrep_calibration,
    ):
        assert handler in pgrep.pgrep_post_handlers


def test_handlers_reachable_at_the_frontend_endpoints():
    # mediasrv exposes each handler at POST /_anki/<camelCase(name)>; the Progress
    # surface calls exactly these names via pgrepCall.
    for endpoint in (
        "pgrepPerformanceScore",
        "pgrepReadinessScore",
        "pgrepCalibration",
    ):
        assert endpoint in mediasrv.post_handlers


def test_exam_handlers_are_registered():
    # The four L5.9 Exam-mode handlers the exam surface calls via pgrepCall.
    for handler in (
        pgrep.pgrep_exam_start,
        pgrep.pgrep_exam_next,
        pgrep.pgrep_exam_answer,
        pgrep.pgrep_exam_result,
    ):
        assert handler in pgrep.pgrep_post_handlers


def test_exam_endpoints_reachable_at_the_frontend_endpoints():
    for endpoint in (
        "pgrepExamStart",
        "pgrepExamNext",
        "pgrepExamAnswer",
        "pgrepExamResult",
    ):
        assert endpoint in mediasrv.post_handlers


def test_exam_start_handler_returns_expected_shape(bridge):
    data = json.loads(pgrep.pgrep_exam_start())

    for key in (
        "session_id",
        "total",
        "duration_s",
        "seconds_per_question",
        "no_help_line",
    ):
        assert key in data, f"missing key: {key}"
    # Empty collection: no Problems to assemble, so the mock has length 0.
    assert data["total"] == 0


# --- handler payloads (shape + honest n=1 state) -----------------------------


def test_performance_handler_returns_expected_shape(bridge):
    data = json.loads(pgrep.pgrep_performance_score())

    assert set(data) == {
        "overall",
        "by_topic",
        "k_perf",
        "coverage_pct",
        "coverage_gate",
        "last_updated",
    }
    # n=1 reality: empty attempt log -> the overall Performance abstains.
    assert data["overall"]["abstain"] is True
    assert data["last_updated"] is None


def test_readiness_handler_returns_expected_shape_and_abstains(bridge):
    data = json.loads(pgrep.pgrep_readiness_score())

    for key in (
        "scaled",
        "low",
        "high",
        "coverage_pct",
        "coverage_gate",
        "abstain",
        "reason",
        "uncovered_topics",
        "by_topic",
    ):
        assert key in data, f"missing key: {key}"
    # Coverage is 0 with no attempts, so Readiness abstains and names the exam.
    assert data["abstain"] is True
    assert data["scaled"] is None
    assert data["coverage_pct"] == 0.0
    assert data["reason"] == "Not enough of the exam is covered yet"
    assert len(data["uncovered_topics"]) > 0


def test_calibration_handler_returns_embedded_evidence(bridge):
    data = json.loads(pgrep.pgrep_calibration())

    assert set(data) >= {"memory", "performance"}
    for layer_name in ("memory", "performance"):
        layer = data[layer_name]
        for key in ("points", "brier", "n", "note"):
            assert key in layer, f"{layer_name} missing key: {key}"
        assert layer["points"], f"{layer_name} should ship reliability points"
        for point in layer["points"]:
            assert set(point) == {"p", "o"}
    # The embedded evidence is present regardless of the (empty) collection.
    assert round(data["memory"]["brier"], 3) == 0.234
    assert round(data["performance"]["brier"], 3) == 0.175


def test_calibration_handler_needs_no_collection():
    # Calibration is pure embedded constants: it must work without aqt.mw.col set.
    data = json.loads(pgrep.pgrep_calibration())
    assert data["memory"]["n"] == 7503
    assert data["performance"]["n"] == 160


# --- login gate (beta) -------------------------------------------------------
# The gate handlers touch the profile manager and (on sign-in) the sync flow, so
# these tests drive them against small fakes: a profile manager that records
# stored auth and the per-device skip flag, a taskman that runs the main-thread
# closure synchronously, and a collection whose sync_login returns an auth or
# raises. Offline-first is never exercised here because the gate never gates it.
# The shell operation coordinator has focused coverage in test_pgrep_operation.py.


class _FakePM:
    """A minimal profile manager: records sync auth and the per-device skip flag."""

    def __init__(self, *, signed_in: bool = False, skipped: bool = False) -> None:
        self._auth: object | None = object() if signed_in else None
        self.meta: dict = {}
        if skipped:
            self.meta["pgrep_login_gate_skipped"] = True
        self.saved = 0
        self.custom_url: str | None = None
        self.sync_key: str | None = None
        self.sync_username: str | None = None

    def sync_auth(self) -> object | None:
        return self._auth

    def set_custom_sync_url(self, url: str | None) -> None:
        self.custom_url = url

    def set_sync_key(self, key: str | None) -> None:
        self.sync_key = key
        self._auth = object() if key else None

    def set_sync_username(self, username: str | None) -> None:
        self.sync_username = username

    def save(self) -> None:
        self.saved += 1


class _RunNowTaskman:
    """run_on_main runs the closure immediately, so side effects are testable."""

    def run_on_main(self, fn) -> None:
        fn()


class _Auth:
    def __init__(self, hkey: str) -> None:
        self.hkey = hkey


class _LoginCol:
    def __init__(
        self, *, result: object = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list = []

    def sync_login(self, *, username: str, password: str, endpoint: str) -> object:
        self.calls.append((username, password, endpoint))
        if self._error is not None:
            raise self._error
        return self._result

    def abort_sync(self) -> None:
        pass


def _fake_mw(pm: _FakePM, col: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(pm=pm, col=col, taskman=_RunNowTaskman())


def test_login_gate_handlers_registered_and_reachable():
    for handler in (
        pgrep.pgrep_auth_status,
        pgrep.pgrep_sign_in,
        pgrep.pgrep_gate_skip,
    ):
        assert handler in pgrep.pgrep_post_handlers
    for endpoint in ("pgrepAuthStatus", "pgrepSignIn", "pgrepGateSkip"):
        assert endpoint in mediasrv.post_handlers


def test_auth_status_first_run_shows_gate(monkeypatch):
    monkeypatch.setattr(aqt, "mw", _fake_mw(_FakePM(), None), raising=False)
    with mediasrv.app.test_request_context(data=b"{}"):
        data = json.loads(pgrep.pgrep_auth_status())
    assert data == {"signed_in": False, "skipped": False, "gate_dismissed": False}


def test_auth_status_dismissed_when_signed_in(monkeypatch):
    monkeypatch.setattr(
        aqt, "mw", _fake_mw(_FakePM(signed_in=True), None), raising=False
    )
    with mediasrv.app.test_request_context(data=b"{}"):
        data = json.loads(pgrep.pgrep_auth_status())
    assert data["signed_in"] is True
    assert data["gate_dismissed"] is True


def test_auth_status_dismissed_when_skipped(monkeypatch):
    monkeypatch.setattr(aqt, "mw", _fake_mw(_FakePM(skipped=True), None), raising=False)
    with mediasrv.app.test_request_context(data=b"{}"):
        data = json.loads(pgrep.pgrep_auth_status())
    assert data["signed_in"] is False
    assert data["skipped"] is True
    assert data["gate_dismissed"] is True


def test_sign_in_requires_credentials(monkeypatch):
    col = _LoginCol(result=_Auth("hkey"))
    monkeypatch.setattr(aqt, "mw", _fake_mw(_FakePM(), col), raising=False)
    with mediasrv.app.test_request_context(
        data=json.dumps({"username": "", "password": ""}).encode()
    ):
        data = json.loads(pgrep.pgrep_sign_in())
    assert data["ok"] is False
    assert "username and password" in data["error"].lower()
    assert col.calls == []  # never hit the server


def test_sign_in_success_stores_key_and_clears_skip(monkeypatch):
    recorded: dict = {}
    monkeypatch.setattr(
        "aqt.sync.sync_collection",
        lambda mw, on_done, *, ui: recorded.update(synced=True, ui=ui),
    )
    col = _LoginCol(result=_Auth("secret-hkey"))
    # A prior offline skip must be cleared once the user actually signs in.
    pm = _FakePM(skipped=True)
    monkeypatch.setattr(aqt, "mw", _fake_mw(pm, col), raising=False)
    with mediasrv.app.test_request_context(
        data=json.dumps(
            {"username": "frank", "password": "physics", "url": "http://host:8090/"}
        ).encode()
    ):
        data = json.loads(pgrep.pgrep_sign_in())
    assert data["ok"] is True
    assert isinstance(data["operation_id"], int)
    assert col.calls == [("frank", "physics", "http://host:8090/")]
    assert pm.sync_key == "secret-hkey"
    assert pm.sync_username == "frank"
    assert pm.custom_url == "http://host:8090/"
    assert "pgrep_login_gate_skipped" not in pm.meta
    assert pm.saved >= 1
    assert recorded.get("synced") is True
    assert recorded["ui"].operation_id == data["operation_id"]


def test_sign_in_reports_bad_credentials(monkeypatch):
    err = SyncError.__new__(SyncError)
    err.kind = SyncErrorKind.AUTH
    col = _LoginCol(error=err)
    pm = _FakePM()
    monkeypatch.setattr(aqt, "mw", _fake_mw(pm, col), raising=False)
    with mediasrv.app.test_request_context(
        data=json.dumps({"username": "frank", "password": "wrong"}).encode()
    ):
        data = json.loads(pgrep.pgrep_sign_in())
    assert data["ok"] is False
    assert "did not match" in data["error"]
    assert pm.sync_key is None  # nothing stored on failure


def test_sign_in_reports_unreachable_server(monkeypatch):
    err = NetworkError.__new__(NetworkError)
    col = _LoginCol(error=err)
    monkeypatch.setattr(aqt, "mw", _fake_mw(_FakePM(), col), raising=False)
    with mediasrv.app.test_request_context(
        data=json.dumps({"username": "frank", "password": "physics"}).encode()
    ):
        data = json.loads(pgrep.pgrep_sign_in())
    assert data["ok"] is False
    assert "reach the server" in data["error"].lower()


def test_gate_skip_persists_and_dismisses(monkeypatch):
    pm = _FakePM()
    monkeypatch.setattr(aqt, "mw", _fake_mw(pm, None), raising=False)
    with mediasrv.app.test_request_context(data=b"{}"):
        data = json.loads(pgrep.pgrep_gate_skip())
    assert data == {"ok": True, "skipped": True}
    assert pm.meta.get("pgrep_login_gate_skipped") is True
    assert pm.saved >= 1
    # The status now reports the gate dismissed.
    with mediasrv.app.test_request_context(data=b"{}"):
        status = json.loads(pgrep.pgrep_auth_status())
    assert status["gate_dismissed"] is True


# --- in-app operations -------------------------------------------------------


def test_operation_handlers_registered_and_reachable():
    handlers = (
        pgrep.pgrep_operation_status,
        pgrep.pgrep_operation_resolve,
        pgrep.pgrep_operation_cancel,
        pgrep.pgrep_operation_dismiss,
    )
    for handler in handlers:
        assert handler in pgrep.pgrep_post_handlers
    for endpoint in (
        "pgrepOperationStatus",
        "pgrepOperationResolve",
        "pgrepOperationCancel",
        "pgrepOperationDismiss",
    ):
        assert endpoint in mediasrv.post_handlers


def test_operation_status_and_stale_resolve(monkeypatch):
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    operation_id = controller.begin("sync", "Checking")
    controller.request_decision(
        operation_id,
        title="Choose",
        body="Keep one copy",
        choices=[{"id": "cancel", "label": "Cancel", "destructive": False}],
        resolver=lambda _choice: None,
    )
    monkeypatch.setattr(
        aqt,
        "mw",
        types.SimpleNamespace(taskman=_RunNowTaskman()),
        raising=False,
    )

    with mediasrv.app.test_request_context(data=b"{}"):
        status = json.loads(pgrep.pgrep_operation_status())
    assert status["operation_id"] == operation_id
    assert status["phase"] == "decision"

    with mediasrv.app.test_request_context(
        data=json.dumps({"operation_id": operation_id + 1, "choice": "cancel"}).encode()
    ):
        resolved = json.loads(pgrep.pgrep_operation_resolve())
    assert resolved == {"ok": False}
    assert controller.snapshot()["phase"] == "decision"


def test_operation_cancel_and_dismiss(monkeypatch):
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    aborted: list[bool] = []
    operation_id = controller.begin(
        "sync", "Syncing", cancellable=True, cancel=lambda: aborted.append(True)
    )
    monkeypatch.setattr(
        aqt,
        "mw",
        types.SimpleNamespace(taskman=_RunNowTaskman()),
        raising=False,
    )

    with mediasrv.app.test_request_context(
        data=json.dumps({"operation_id": operation_id}).encode()
    ):
        cancelled = json.loads(pgrep.pgrep_operation_cancel())
    assert cancelled == {"ok": True}
    assert aborted == [True]

    controller.fail(operation_id, "Sync failed")
    with mediasrv.app.test_request_context(
        data=json.dumps({"operation_id": operation_id}).encode()
    ):
        dismissed = json.loads(pgrep.pgrep_operation_dismiss())
    assert dismissed == {"ok": True}
    assert controller.snapshot()["phase"] == "idle"


def test_sync_handler_starts_product_ui(monkeypatch):
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    captured: dict = {}
    monkeypatch.setattr(
        "aqt.sync.sync_collection",
        lambda mw, on_done, *, ui: captured.update(ui=ui),
    )
    pm = _FakePM(signed_in=True)
    col = types.SimpleNamespace(abort_sync=lambda: None)
    monkeypatch.setattr(aqt, "mw", _fake_mw(pm, col), raising=False)

    with mediasrv.app.test_request_context(data=b"{}"):
        result = json.loads(pgrep.pgrep_sync())

    assert result["status"] == "started"
    assert isinstance(captured["ui"], ProductSyncUi)
    assert result["operation_id"] == captured["ui"].operation_id


def test_export_reports_success_without_qt_progress(monkeypatch):
    controller = OperationController()
    monkeypatch.setattr(pgrep_operation, "operation_controller", controller)
    reopened: list[bool] = []

    class FakeQueryOp:
        def __init__(self, *, parent, op, success) -> None:
            self.op = op
            self.success = success
            self.failure_callback = None

        def failure(self, callback):
            self.failure_callback = callback
            return self

        def run_in_background(self) -> None:
            self.success(None)

    monkeypatch.setattr("aqt.operations.QueryOp", FakeQueryOp)
    monkeypatch.setattr(
        "anki.pgrep.settings.default_export_path", lambda: "/tmp/pgrep.colpkg"
    )
    monkeypatch.setattr(
        "aqt.gui_hooks.collection_will_temporarily_close", lambda _col: None
    )
    monkeypatch.setattr(
        aqt,
        "mw",
        types.SimpleNamespace(
            col=object(),
            taskman=_RunNowTaskman(),
            reopen=lambda: reopened.append(True),
        ),
        raising=False,
    )

    with mediasrv.app.test_request_context(data=b"{}"):
        result = json.loads(pgrep.pgrep_export())

    assert result["status"] == "started"
    assert result["operation_id"] == controller.snapshot()["operation_id"]
    assert controller.snapshot()["phase"] == "success"
    assert reopened == [True]
