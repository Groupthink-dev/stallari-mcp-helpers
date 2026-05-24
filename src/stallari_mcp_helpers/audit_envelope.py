"""Canonical ``_meta: {...}`` audit-envelope builder.

Renders the JSON-tail audit envelope locked by DD-338 Phase A.1 wire contract.
Single line appended after ``\\n\\n``; assembler regex on the consuming side::

    ENVELOPE_RX = re.compile(r"^_meta: (\\{.*\\})$", re.MULTILINE)

Locked encoding:

    1. **JSON separator** ``(",", ":")`` — tight, byte-minimal.
    2. **filtered_by** sorted alphabetically for hash reproducibility.
    3. **ensure_ascii=False** — preserve Unicode.
    4. **Field-presence rules:**
       - ``latency_ms`` — always present.
       - ``filtered_by``, ``redactions`` — always present; default ``[]``.
       - ``next_cursor`` — always present; defaults to JSON ``null``.
       - ``matched_total``, ``returned`` — omitted entirely when ``None``
         (relaxed in v0.3.0; write-tier callers omit these read-tier fields).
       - ``rows_affected``, ``target_id``, ``write_durability``,
         ``response_timestamp`` — omitted entirely when ``None`` (new in
         v0.3.0; write-tier audit fields).
       - ``error_notes``, ``domain_hints`` — omitted entirely when ``None`` or
         empty (Convention #22 graceful degradation).
    5. **Canonical key order** (when present, in this exact order)::

           matched_total, returned, filtered_by, latency_ms, redactions,
           next_cursor, rows_affected, target_id, write_durability,
           response_timestamp, error_notes, domain_hints

       JSON is hand-assembled rather than emitted through a single
       ``json.dumps(dict, ...)`` call because Python's standard JSON encoder
       does not guarantee key insertion order across versions/implementations
       in the way the cross-language byte-parity invariant requires. Each
       present field is rendered individually via ``json.dumps`` (preserving
       the locked separators + ``ensure_ascii=False`` for the value), then
       concatenated in canonical order.
    6. **Kwarg-only signature** — forces call-site clarity.
"""

from __future__ import annotations

import json
from typing import Any

# Canonical key order — must stay byte-identical with TS + Swift sibling helpers.
_CANONICAL_KEYS: tuple[str, ...] = (
    "matched_total",
    "returned",
    "filtered_by",
    "latency_ms",
    "redactions",
    "next_cursor",
    "rows_affected",
    "target_id",
    "write_durability",
    "response_timestamp",
    "error_notes",
    "domain_hints",
)


def meta_envelope(
    *,
    latency_ms: int,
    matched_total: int | None = None,
    returned: int | None = None,
    filtered_by: list[str] | None = None,
    redactions: list[str] | None = None,
    next_cursor: str | None = None,
    rows_affected: int | None = None,
    target_id: str | None = None,
    write_durability: str | None = None,
    response_timestamp: str | None = None,
    error_notes: list[str] | None = None,
    domain_hints: dict[str, str] | None = None,
) -> str:
    """Render the canonical ``_meta: {...}`` JSON-tail envelope line.

    Returns the literal line ``_meta: {"...": ..., ...}`` — no leading
    newlines. Caller appends to body with ``\\n\\n`` (see
    :func:`append_meta`).

    Read-tier fields (``matched_total``, ``returned``) are omitted when
    ``None``. Write-tier fields (``rows_affected``, ``target_id``,
    ``write_durability``, ``response_timestamp``) are omitted when ``None``.
    ``filtered_by`` is sorted alphabetically for byte-equality determinism
    across call sites that pass the same logical filter set in different
    orders.

    ``write_durability`` accepts any string; the canonical values are
    ``"edge"``, ``"central"``, and ``"replicated"`` but no enum is enforced
    at this layer (kept callable from upstream APIs whose vocabulary may
    extend over time).
    """
    # Build the set of present (key, value) pairs honouring canonical order.
    present: dict[str, Any] = {}

    if matched_total is not None:
        present["matched_total"] = matched_total
    if returned is not None:
        present["returned"] = returned
    present["filtered_by"] = sorted(filtered_by) if filtered_by else []
    present["latency_ms"] = latency_ms
    present["redactions"] = list(redactions) if redactions else []
    present["next_cursor"] = next_cursor
    if rows_affected is not None:
        present["rows_affected"] = rows_affected
    if target_id is not None:
        present["target_id"] = target_id
    if write_durability is not None:
        present["write_durability"] = write_durability
    if response_timestamp is not None:
        present["response_timestamp"] = response_timestamp
    if error_notes:
        present["error_notes"] = list(error_notes)
    if domain_hints:
        present["domain_hints"] = domain_hints

    # Hand-assemble in canonical order — see module-level note on why we do
    # not trust ``json.dumps(dict)`` for cross-language byte-parity.
    parts: list[str] = []
    for key in _CANONICAL_KEYS:
        if key not in present:
            continue
        encoded_key = json.dumps(key, ensure_ascii=False)
        encoded_value = json.dumps(
            present[key], separators=(",", ":"), ensure_ascii=False
        )
        parts.append(f"{encoded_key}:{encoded_value}")

    return "_meta: {" + ",".join(parts) + "}"


def append_meta(body: str, meta_line: str) -> str:
    """Append a ``_meta: {...}`` line to a body with ``\\n\\n`` joiner.

    The joiner is two newlines regardless of whether ``body`` is empty —
    the assembler-side regex ``r"\\n\\n_meta: (\\{.*\\})$"`` still matches
    at end-of-string in the empty-body case.
    """
    return body + "\n\n" + meta_line
