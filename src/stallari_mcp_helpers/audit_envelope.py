"""Canonical ``_meta: {...}`` audit-envelope builder.

Renders the JSON-tail audit envelope locked by DD-338 Phase A.1 wire contract.
Single line appended after ``\\n\\n``; assembler regex on the consuming side::

    ENVELOPE_RX = re.compile(r"^_meta: (\\{.*\\})$", re.MULTILINE)

Locked encoding:

    1. **JSON separator** ``(",", ":")`` — tight, byte-minimal.
    2. **filtered_by** sorted alphabetically for hash reproducibility.
    3. **ensure_ascii=False** — preserve Unicode.
    4. **Field-presence rules:**
       - ``matched_total``, ``returned``, ``latency_ms``, ``filtered_by``,
         ``redactions``, ``next_cursor`` — always present. ``filtered_by`` and
         ``redactions`` default to ``[]``; ``next_cursor`` defaults to JSON
         ``null``.
       - ``error_notes``, ``domain_hints`` — omitted entirely when ``None`` or
         empty (Convention #22 graceful degradation).
    5. **Kwarg-only signature** — forces call-site clarity.
"""

from __future__ import annotations

import json
from typing import Any


def meta_envelope(
    *,
    matched_total: int,
    returned: int,
    latency_ms: int,
    filtered_by: list[str] | None = None,
    redactions: list[str] | None = None,
    next_cursor: str | None = None,
    error_notes: list[str] | None = None,
    domain_hints: dict[str, str] | None = None,
) -> str:
    """Render the canonical ``_meta: {...}`` JSON-tail envelope line.

    Returns the literal line ``_meta: {"matched_total": ..., ...}`` — no
    leading newlines. Caller appends to body with ``\\n\\n`` (see
    :func:`append_meta`).

    Required fields are always serialized; optional fields (``error_notes``,
    ``domain_hints``) are omitted when ``None`` or empty per Convention #22.
    ``filtered_by`` is sorted alphabetically for byte-equality determinism
    across call sites that pass the same logical filter set in different
    orders.
    """
    payload: dict[str, Any] = {
        "matched_total": matched_total,
        "returned": returned,
        "latency_ms": latency_ms,
        "filtered_by": sorted(filtered_by) if filtered_by else [],
        "redactions": list(redactions) if redactions else [],
        "next_cursor": next_cursor,
    }
    if error_notes:
        payload["error_notes"] = list(error_notes)
    if domain_hints:
        payload["domain_hints"] = domain_hints
    return "_meta: " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def append_meta(body: str, meta_line: str) -> str:
    """Append a ``_meta: {...}`` line to a body with ``\\n\\n`` joiner.

    The joiner is two newlines regardless of whether ``body`` is empty —
    the assembler-side regex ``r"\\n\\n_meta: (\\{.*\\})$"`` still matches
    at end-of-string in the empty-body case.
    """
    return body + "\n\n" + meta_line
