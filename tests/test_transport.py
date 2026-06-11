"""Tests for the canonical HTTP-transport policy gate (AUD-04-08/09/19/31)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stallari_mcp_helpers.transport import (
    BearerAuthASGIMiddleware,
    HTTPTransportConfig,
    TransportPolicyError,
    resolve_http_transport,
    run_http,
    strict_env_bool,
)

PREFIX = "TESTBLADE"


def _env(**kwargs: str) -> dict[str, str]:
    return {f"{PREFIX}_MCP_{k}": v for k, v in kwargs.items()}


# ---------------------------------------------------------------------------
# strict_env_bool — the truthy-string-parse defect class
# ---------------------------------------------------------------------------


def test_strict_env_bool_only_exact_true() -> None:
    assert strict_env_bool("true") is True
    for bad in ("True", "TRUE", "1", "yes", "on", " true", "true ", "", None):
        assert strict_env_bool(bad) is False, bad


# ---------------------------------------------------------------------------
# resolve_http_transport — refusal matrix
# ---------------------------------------------------------------------------


def test_token_absent_refuses() -> None:
    with pytest.raises(TransportPolicyError, match="refuses to serve"):
        resolve_http_transport(env_prefix=PREFIX, default_port=9000, env={})


def test_token_empty_or_whitespace_refuses() -> None:
    for tok in ("", "   "):
        with pytest.raises(TransportPolicyError):
            resolve_http_transport(env_prefix=PREFIX, default_port=9000, env=_env(TOKEN=tok))


def test_token_present_loopback_default_ok() -> None:
    cfg = resolve_http_transport(env_prefix=PREFIX, default_port=9000, env=_env(TOKEN="s3cret"))
    assert cfg == HTTPTransportConfig(host="127.0.0.1", port=9000, token="s3cret")


def test_wildcard_bind_refused_even_with_token_and_optin() -> None:
    for host in ("0.0.0.0", "::", "[::]"):
        with pytest.raises(TransportPolicyError, match="wildcard"):
            resolve_http_transport(
                env_prefix=PREFIX,
                default_port=9000,
                env=_env(TOKEN="s3cret", HOST=host, ALLOW_NONLOOPBACK="true"),
            )


def test_nonloopback_requires_strict_optin() -> None:
    env = _env(TOKEN="s3cret", HOST="192.168.1.10")
    with pytest.raises(TransportPolicyError, match="ALLOW_NONLOOPBACK"):
        resolve_http_transport(env_prefix=PREFIX, default_port=9000, env=env)
    # Truthy-but-not-exact strings stay refused.
    env[f"{PREFIX}_MCP_ALLOW_NONLOOPBACK"] = "1"
    with pytest.raises(TransportPolicyError):
        resolve_http_transport(env_prefix=PREFIX, default_port=9000, env=env)
    env[f"{PREFIX}_MCP_ALLOW_NONLOOPBACK"] = "true"
    cfg = resolve_http_transport(env_prefix=PREFIX, default_port=9000, env=env)
    assert cfg.host == "192.168.1.10"


def test_loopback_variants_ok_without_optin() -> None:
    for host in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
        cfg = resolve_http_transport(
            env_prefix=PREFIX,
            default_port=9000,
            env=_env(TOKEN="s3cret", HOST=host),
        )
        assert cfg.host == host


def test_port_parse_strict_and_range() -> None:
    cfg = resolve_http_transport(
        env_prefix=PREFIX, default_port=9000, env=_env(TOKEN="t", PORT="8123")
    )
    assert cfg.port == 8123
    for bad in ("abc", "0", "65536", "-1"):
        with pytest.raises(TransportPolicyError):
            resolve_http_transport(
                env_prefix=PREFIX, default_port=9000, env=_env(TOKEN="t", PORT=bad)
            )


def test_legacy_token_var_override() -> None:
    cfg = resolve_http_transport(
        env_prefix=PREFIX,
        default_port=9000,
        env={"THINGS_MCP_API_TOKEN": "legacy"},
        token_var="THINGS_MCP_API_TOKEN",
    )
    assert cfg.token == "legacy"


# ---------------------------------------------------------------------------
# BearerAuthASGIMiddleware — enforcement incl. websocket scope
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.app_called = False

    async def app(self, scope: Any, receive: Any, send: Any) -> None:
        self.app_called = True

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def _scope(scope_type: str, auth: str | None) -> dict[str, Any]:
    headers = [(b"authorization", auth.encode("latin-1"))] if auth is not None else []
    return {"type": scope_type, "headers": headers}


def _run(mw: BearerAuthASGIMiddleware, scope: dict[str, Any], rec: _Recorder) -> None:
    asyncio.run(mw(scope, None, rec.send))


def test_http_valid_bearer_passes_through() -> None:
    rec = _Recorder()
    mw = BearerAuthASGIMiddleware(rec.app, token="tok")
    _run(mw, _scope("http", "Bearer tok"), rec)
    assert rec.app_called and rec.messages == []


@pytest.mark.parametrize(
    "auth",
    [None, "Bearer wrong", "Basic dXNlcg==", "Bearer", "bearer  ", "tok"],
)
def test_http_missing_or_bad_credentials_401(auth: str | None) -> None:
    rec = _Recorder()
    mw = BearerAuthASGIMiddleware(rec.app, token="tok")
    _run(mw, _scope("http", auth), rec)
    assert not rec.app_called
    start = rec.messages[0]
    assert start["status"] == 401
    assert (b"www-authenticate", b"Bearer") in start["headers"]
    # The expected token never appears in the rejection.
    assert b"tok" not in rec.messages[1]["body"]


def test_websocket_scope_is_enforced_not_exempted() -> None:
    """AUD-04-31 — a websocket-exempting bearer gate is a bypass."""
    rec = _Recorder()
    mw = BearerAuthASGIMiddleware(rec.app, token="tok")
    _run(mw, _scope("websocket", None), rec)
    assert not rec.app_called
    assert rec.messages == [{"type": "websocket.close", "code": 4401}]

    rec2 = _Recorder()
    mw2 = BearerAuthASGIMiddleware(rec2.app, token="tok")
    _run(mw2, _scope("websocket", "Bearer tok"), rec2)
    assert rec2.app_called


def test_lifespan_scope_passes_through() -> None:
    rec = _Recorder()
    mw = BearerAuthASGIMiddleware(rec.app, token="tok")
    _run(mw, {"type": "lifespan", "headers": []}, rec)
    assert rec.app_called


def test_middleware_refuses_empty_token_at_wiring_time() -> None:
    with pytest.raises(TransportPolicyError):
        BearerAuthASGIMiddleware(lambda *a: None, token="")


def test_bearer_case_insensitive_scheme() -> None:
    rec = _Recorder()
    mw = BearerAuthASGIMiddleware(rec.app, token="tok")
    _run(mw, _scope("http", "bearer tok"), rec)
    assert rec.app_called


# ---------------------------------------------------------------------------
# run_http — FastMCP 3.x kwargs shape (AUD-04-09)
# ---------------------------------------------------------------------------


def test_run_http_uses_fastmcp3_run_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The glue must call mcp.run(transport=, host=, port=, middleware=) —
    never touch mcp.settings (dead on FastMCP 3.x)."""

    class FakeMCP:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def run(self, **kwargs: Any) -> None:
            self.calls.append(kwargs)

        def __getattr__(self, name: str) -> Any:
            if name == "settings":
                raise AssertionError("run_http touched mcp.settings — dead on FastMCP 3.x")
            raise AttributeError(name)

    # Stub starlette if absent in the test env.
    import sys
    import types

    if "starlette.middleware" not in sys.modules:
        starlette = types.ModuleType("starlette")
        middleware_mod = types.ModuleType("starlette.middleware")

        class Middleware:
            def __init__(self, cls: Any, **kwargs: Any) -> None:
                self.cls = cls
                self.kwargs = kwargs

        middleware_mod.Middleware = Middleware  # type: ignore[attr-defined]
        starlette.middleware = middleware_mod  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "starlette", starlette)
        monkeypatch.setitem(sys.modules, "starlette.middleware", middleware_mod)

    mcp = FakeMCP()
    cfg = HTTPTransportConfig(host="127.0.0.1", port=8771, token="tok")
    run_http(mcp, cfg)
    assert len(mcp.calls) == 1
    call = mcp.calls[0]
    assert call["transport"] == "http"
    assert call["host"] == "127.0.0.1"
    assert call["port"] == 8771
    (mw,) = call["middleware"]
    assert mw.cls is BearerAuthASGIMiddleware
    assert mw.kwargs == {"token": "tok"}
