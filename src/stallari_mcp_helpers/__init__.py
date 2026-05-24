"""Canonical helpers for Stallari-conformant MCP servers.

Public API:

- :func:`meta_envelope` / :func:`append_meta` — render and append the
  canonical ``_meta: {...}`` JSON-tail audit envelope.
- :class:`Pattern` / :func:`compute_domain_hint` / :func:`load_patterns_from_yaml` —
  per-record domain-hint attribution engine.
- :func:`lint_blade` / :class:`LintResult` — static audit-surface honesty
  linter (DD-338 Phase B Python implementation of S-AUD-001).

See ``CHANGELOG.md`` for the full surface and DD-338 for the design record.
"""

from __future__ import annotations

from .audit_envelope import append_meta, meta_envelope
from .domain_hint import Pattern, compute_domain_hint, load_patterns_from_yaml
from .lint import LintResult, lint_blade

__version__ = "0.2.0"

__all__ = [
    "LintResult",
    "Pattern",
    "__version__",
    "append_meta",
    "compute_domain_hint",
    "lint_blade",
    "load_patterns_from_yaml",
    "meta_envelope",
]
