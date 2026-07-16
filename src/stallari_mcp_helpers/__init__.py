"""Canonical helpers for Stallari-conformant MCP servers.

Public API:

- :func:`meta_envelope` / :func:`append_meta` — render and append the
  canonical ``_meta: {...}`` JSON-tail audit envelope.
- :class:`Pattern` / :func:`compute_domain_hint` / :func:`load_patterns_from_yaml` —
  per-record domain-hint attribution engine.
- :func:`lint_blade` / :class:`LintResult` — static audit-surface honesty
  linter (DD-338 Phase B Python implementation of S-AUD-001).
- :func:`resolve_http_transport` / :func:`run_http` /
  :class:`BearerAuthASGIMiddleware` — canonical HTTP-transport policy gate
  (token-absent ⇒ refuse-to-serve; FastMCP 3.x serving glue; DD-386).

See ``CHANGELOG.md`` for the full surface and DD-338 / DD-386 for the
design records.
"""

from __future__ import annotations

from .audit_envelope import append_meta, meta_envelope
from .domain_hint import Pattern, compute_domain_hint, load_patterns_from_yaml
from .lint import LintResult, lint_blade
from .transport import (
    BearerAuthASGIMiddleware,
    HTTPTransportConfig,
    TransportPolicyError,
    http_middleware,
    resolve_http_transport,
    run_http,
    strict_env_bool,
)

__version__ = "0.4.1"

__all__ = [
    "BearerAuthASGIMiddleware",
    "HTTPTransportConfig",
    "LintResult",
    "Pattern",
    "TransportPolicyError",
    "__version__",
    "append_meta",
    "compute_domain_hint",
    "http_middleware",
    "lint_blade",
    "load_patterns_from_yaml",
    "meta_envelope",
    "resolve_http_transport",
    "run_http",
    "strict_env_bool",
]
