"""Canonical HTTP-transport policy gate for Stallari-conformant MCP servers.

Closes the fleet-wide AUD-04-08 / AUD-04-09 / AUD-04-19 / AUD-04-31 defect
classes once, at the shared-lib layer, instead of per blade:

- **Token-absent ⇒ refuse-to-serve.** Manual HTTP mode without a bearer
  token must *refuse to start*, never warn-and-serve unauthenticated
  (access-policy: "require a bearer token — never unauthenticated").
- **Wildcard bind ⇒ refuse.** ``0.0.0.0`` / ``::`` / empty-host binds are
  refused unconditionally (access-policy: "never 0.0.0.0"). A specific
  non-loopback address additionally requires the explicit
  ``{PREFIX}_MCP_ALLOW_NONLOOPBACK=true`` opt-in.
- **Strict boolean env parse.** Only the exact string ``"true"`` enables a
  gate — no truthy-string drift (``"1"``, ``"yes"``, ``"True"`` are all
  *false*; the paddle-billing gate posture).
- **FastMCP 3.x-correct serving glue.** The ``mcp.settings.http_app_kwargs``
  idiom is dead on FastMCP 3.x (no ``settings`` attribute — HTTP mode
  crashes with ``AttributeError`` at startup). :func:`http_middleware` /
  :func:`run_http` wrap the working pattern::

      mcp.run(transport="http", host=cfg.host, port=cfg.port,
              middleware=http_middleware(cfg))

- **Bearer enforcement covers websocket scopes** and compares in constant
  time. The middleware never logs or echoes the expected token.

Stdlib-only at import time; ``starlette`` is imported lazily inside
:func:`http_middleware` (every FastMCP blade already ships it
transitively).

Usage (blade ``__main__`` / ``server.py``)::

    from stallari_mcp_helpers.transport import (
        TransportPolicyError, resolve_http_transport, run_http,
    )

    if transport == "http":
        try:
            cfg = resolve_http_transport(env_prefix="CALDAV", default_port=8771)
        except TransportPolicyError as e:
            print(f"refusing to serve HTTP: {e}", file=sys.stderr)
            raise SystemExit(2)
        run_http(mcp, cfg)
    else:
        mcp.run()  # stdio — the harness-launch posture (DD-242)
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BearerAuthASGIMiddleware",
    "HTTPTransportConfig",
    "TransportPolicyError",
    "http_middleware",
    "resolve_http_transport",
    "run_http",
    "strict_env_bool",
]

_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "[::]", ""})  # refused, not bound
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})


class TransportPolicyError(Exception):
    """HTTP transport configuration violates the Stallari serving policy.

    Raised by :func:`resolve_http_transport` *before* any socket is opened.
    The message is operator-actionable and never contains secret material.
    """


@dataclass(frozen=True)
class HTTPTransportConfig:
    """Resolved, policy-clean HTTP serving parameters.

    Instances are only ever produced by :func:`resolve_http_transport`,
    so holding one is proof the policy gate passed: ``token`` is non-empty
    and ``host`` is loopback or explicitly opted-in non-loopback.
    """

    host: str
    port: int
    token: str


def strict_env_bool(value: str | None) -> bool:
    """Strict boolean env parse: only the exact string ``"true"`` is True.

    The fleet's recurring truthy-string-parse defect class (AUD-04 §cross-
    cutting) is avoided by refusing to interpret ``"1"``, ``"yes"``,
    ``"True"``, etc. Case-sensitive by design — match the documented value
    exactly or the gate stays closed.
    """
    return value == "true"


def _is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def resolve_http_transport(
    *,
    env_prefix: str,
    default_port: int,
    env: Mapping[str, str] | None = None,
    token_var: str | None = None,
) -> HTTPTransportConfig:
    """Resolve + police HTTP serving parameters from the environment.

    Reads ``{env_prefix}_MCP_HOST`` (default ``127.0.0.1``),
    ``{env_prefix}_MCP_PORT`` (default ``default_port``),
    ``{env_prefix}_MCP_TOKEN`` (or ``token_var`` when a blade carries a
    legacy token variable name), and
    ``{env_prefix}_MCP_ALLOW_NONLOOPBACK`` (strict-bool).

    Raises :class:`TransportPolicyError` when:

    - the token variable is unset or empty (**token-absent ⇒
      refuse-to-serve** — never warn-and-serve unauthenticated);
    - the host is a wildcard bind (``0.0.0.0`` / ``::`` / empty) — refused
      unconditionally;
    - the host is a specific non-loopback address and
      ``{env_prefix}_MCP_ALLOW_NONLOOPBACK`` is not exactly ``"true"``;
    - the port is not an integer in 1-65535.
    """
    e = os.environ if env is None else env
    token_name = token_var or f"{env_prefix}_MCP_TOKEN"
    token = e.get(token_name, "")
    if not token.strip():
        raise TransportPolicyError(
            f"{token_name} is unset or empty — HTTP mode requires a bearer "
            "token and refuses to serve without one. Set "
            f"{token_name} to a strong secret, or use the default stdio "
            "transport which needs no token."
        )

    host = e.get(f"{env_prefix}_MCP_HOST", "127.0.0.1").strip()
    if host in _WILDCARD_HOSTS:
        raise TransportPolicyError(
            f"{env_prefix}_MCP_HOST={host!r} is a wildcard bind, which is "
            "never permitted (access-policy: never 0.0.0.0). Bind a "
            "specific interface address instead, and set "
            f"{env_prefix}_MCP_ALLOW_NONLOOPBACK=true if that address is "
            "not loopback."
        )
    if not _is_loopback(host) and not strict_env_bool(
        e.get(f"{env_prefix}_MCP_ALLOW_NONLOOPBACK")
    ):
        raise TransportPolicyError(
            f"{env_prefix}_MCP_HOST={host!r} is not a loopback address. "
            f"Set {env_prefix}_MCP_ALLOW_NONLOOPBACK=true (exact string) "
            "to opt in to non-loopback serving — the bearer token is "
            "still required."
        )

    raw_port = e.get(f"{env_prefix}_MCP_PORT", "").strip()
    if raw_port:
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise TransportPolicyError(
                f"{env_prefix}_MCP_PORT={raw_port!r} is not an integer."
            ) from exc
    else:
        port = default_port
    if not 1 <= port <= 65535:
        raise TransportPolicyError(
            f"{env_prefix}_MCP_PORT={port} is outside 1-65535."
        )

    return HTTPTransportConfig(host=host, port=port, token=token)


class BearerAuthASGIMiddleware:
    """Pure-ASGI bearer-token gate for **http and websocket** scopes.

    Framework-free (no starlette import) so it can be unit-tested and
    wired into any ASGI stack. Enforcement properties:

    - applies to ``http`` *and* ``websocket`` scopes (AUD-04-31: a
      websocket-exempting gate is a bypass, not a gate); ``lifespan``
      passes through;
    - constant-time comparison via :func:`hmac.compare_digest`;
    - missing/malformed/mismatched credentials ⇒ ``401`` with
      ``WWW-Authenticate: Bearer`` (http) or a ``4401`` close (websocket);
    - the expected token is never logged, echoed, or included in the
      rejection body.
    """

    def __init__(self, app: Any, *, token: str) -> None:
        if not token:
            # Constructing an auth gate with no token would silently
            # recreate AUD-04-08; fail loudly at wiring time instead.
            raise TransportPolicyError(
                "BearerAuthASGIMiddleware requires a non-empty token"
            )
        self.app = app
        self._token = token

    @staticmethod
    def _bearer_from_headers(scope: Mapping[str, Any]) -> str | None:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                try:
                    decoded = bytes(value).decode("latin-1")
                except Exception:
                    return None
                scheme, _, credential = decoded.partition(" ")
                if scheme.lower() == "bearer" and credential:
                    return credential.strip()
                return None
        return None

    def _authorized(self, scope: Mapping[str, Any]) -> bool:
        presented = self._bearer_from_headers(scope)
        if presented is None:
            return False
        return hmac.compare_digest(
            presented.encode("utf-8"), self._token.encode("utf-8")
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"unauthorized"})


def http_middleware(config: HTTPTransportConfig) -> list[Any]:
    """Build the FastMCP 3.x ``middleware=[...]`` list for bearer auth.

    Returns ``[starlette.middleware.Middleware(BearerAuthASGIMiddleware,
    token=...)]`` — the shape ``mcp.run(transport="http", middleware=...)``
    and ``mcp.http_app(middleware=...)`` both accept. ``starlette`` is
    imported lazily (transitively present in every FastMCP install).

    Do **not** assign ``mcp.settings.http_app_kwargs`` — FastMCP 3.x has no
    ``settings`` attribute and the idiom raises ``AttributeError`` at
    startup (AUD-04-09).
    """
    from starlette.middleware import (  # type: ignore[import-not-found]
        Middleware,
    )

    return [Middleware(BearerAuthASGIMiddleware, token=config.token)]


def run_http(mcp: Any, config: HTTPTransportConfig) -> None:
    """Serve a FastMCP 3.x server over HTTP behind the policy gate.

    Equivalent to::

        mcp.run(transport="http", host=config.host, port=config.port,
                middleware=http_middleware(config))

    ``config`` must come from :func:`resolve_http_transport`, so the
    token-present and bind-policy invariants already hold.
    """
    mcp.run(
        transport="http",
        host=config.host,
        port=config.port,
        middleware=http_middleware(config),
    )
