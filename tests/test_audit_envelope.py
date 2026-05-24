"""Tests for ``stallari_mcp_helpers.audit_envelope``.

Coverage target: 100% line + branch on ``audit_envelope.py``.
Spec: ``2026-05-24-dd-338-e-python-mcp-helpers-package.md`` § Test Coverage.

DD-338 Phase D.1 (v0.3.0): extended for write-tier optional fields and
relaxed-required (``matched_total``, ``returned``) read-tier fields.
"""

from __future__ import annotations

import json
import re

import pytest

from stallari_mcp_helpers.audit_envelope import append_meta, meta_envelope

ENVELOPE_RX = re.compile(r"^_meta: (\{.*\})$")


# ---------------------------------------------------------------------------
#  Required-fields-only baseline
# ---------------------------------------------------------------------------


def test_required_fields_only() -> None:
    """Case 1: required kwargs only → all baseline fields present with defaults."""
    line = meta_envelope(matched_total=10, returned=10, latency_ms=42)
    m = ENVELOPE_RX.match(line)
    assert m is not None
    payload = json.loads(m.group(1))
    assert payload == {
        "matched_total": 10,
        "returned": 10,
        "latency_ms": 42,
        "filtered_by": [],
        "redactions": [],
        "next_cursor": None,
    }


def test_required_fields_omit_optional_keys() -> None:
    """error_notes + domain_hints absent from required-only output."""
    line = meta_envelope(matched_total=0, returned=0, latency_ms=1)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "error_notes" not in payload
    assert "domain_hints" not in payload
    # v0.3.0 write-tier fields also absent
    assert "rows_affected" not in payload
    assert "target_id" not in payload
    assert "write_durability" not in payload
    assert "response_timestamp" not in payload


# ---------------------------------------------------------------------------
#  filtered_by — alphabetical sort
# ---------------------------------------------------------------------------


def test_filtered_by_alphabetical_sort() -> None:
    """Case 2: filtered_by sorted alphabetically regardless of input order."""
    line = meta_envelope(
        matched_total=1,
        returned=1,
        latency_ms=1,
        filtered_by=["scope=work", "limit=10", "active=true"],
    )
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["filtered_by"] == ["active=true", "limit=10", "scope=work"]


# ---------------------------------------------------------------------------
#  redactions
# ---------------------------------------------------------------------------


def test_redactions_populated() -> None:
    """Case 3: redactions populated → preserved in output."""
    line = meta_envelope(matched_total=1, returned=1, latency_ms=1, redactions=["pii_email"])
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["redactions"] == ["pii_email"]


# ---------------------------------------------------------------------------
#  error_notes — omit-when-None / omit-when-empty
# ---------------------------------------------------------------------------


def test_error_notes_none_omitted() -> None:
    """Case 4: error_notes=None → key absent from output."""
    line = meta_envelope(matched_total=0, returned=0, latency_ms=1, error_notes=None)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "error_notes" not in payload


def test_error_notes_empty_list_omitted() -> None:
    """Case 5: error_notes=[] → key absent (Convention #22 empty=None-equivalent)."""
    line = meta_envelope(matched_total=0, returned=0, latency_ms=1, error_notes=[])
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "error_notes" not in payload


def test_error_notes_populated() -> None:
    """Case 6: error_notes=['warn1', 'warn2'] → key present with both entries."""
    line = meta_envelope(
        matched_total=1,
        returned=1,
        latency_ms=1,
        error_notes=["warn1", "warn2"],
    )
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["error_notes"] == ["warn1", "warn2"]


# ---------------------------------------------------------------------------
#  domain_hints — omit-when-None / omit-when-empty
# ---------------------------------------------------------------------------


def test_domain_hints_none_omitted() -> None:
    """Case 7: domain_hints=None → key absent."""
    line = meta_envelope(matched_total=0, returned=0, latency_ms=1, domain_hints=None)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "domain_hints" not in payload


def test_domain_hints_empty_dict_omitted() -> None:
    """domain_hints={} → key absent (Convention #22 empty=None-equivalent)."""
    line = meta_envelope(matched_total=0, returned=0, latency_ms=1, domain_hints={})
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "domain_hints" not in payload


def test_domain_hints_populated() -> None:
    """Case 8: domain_hints={...} → key present with entries."""
    line = meta_envelope(
        matched_total=2,
        returned=2,
        latency_ms=1,
        domain_hints={"id1": "work", "id2": "personal"},
    )
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["domain_hints"] == {"id1": "work", "id2": "personal"}


# ---------------------------------------------------------------------------
#  Byte-equality determinism
# ---------------------------------------------------------------------------


def test_byte_equality_determinism() -> None:
    """Case 9: same kwargs called twice → byte-identical output."""
    kwargs = dict(
        matched_total=5,
        returned=5,
        latency_ms=10,
        filtered_by=["b", "a", "c"],
        redactions=["x"],
        next_cursor="cursor-abc",
        error_notes=["note1"],
        domain_hints={"r1": "work"},
    )
    a = meta_envelope(**kwargs)  # type: ignore[arg-type]
    b = meta_envelope(**kwargs)  # type: ignore[arg-type]
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


# ---------------------------------------------------------------------------
#  Unicode preservation
# ---------------------------------------------------------------------------


def test_unicode_preservation_filtered_by() -> None:
    """Case 10: filtered_by with non-ASCII → literal chars preserved (ensure_ascii=False)."""
    line = meta_envelope(matched_total=1, returned=1, latency_ms=1, filtered_by=["scope=日本"])
    assert "日本" in line
    assert r"\u" not in line  # no \uXXXX escapes


def test_unicode_preservation_domain_hints() -> None:
    """Unicode preserved in domain_hints values."""
    line = meta_envelope(
        matched_total=1,
        returned=1,
        latency_ms=1,
        domain_hints={"r1": "家族"},
    )
    assert "家族" in line


# ---------------------------------------------------------------------------
#  Strict separators
# ---------------------------------------------------------------------------


def test_strict_separators() -> None:
    """Case 11: no space after comma or colon — strict canonical form."""
    line = meta_envelope(matched_total=1, returned=1, latency_ms=1)
    body = line[len("_meta: ") :]
    # The JSON body must not contain ", " (comma+space) or ": " (colon+space)
    # outside of literal-string positions. For these baseline kwargs there
    # are no string values containing those sequences.
    assert ", " not in body
    assert ": " not in body


# ---------------------------------------------------------------------------
#  append_meta — joiner semantics
# ---------------------------------------------------------------------------


def test_append_meta_joiner() -> None:
    """Case 12: append_meta joins body and meta with \\n\\n."""
    meta = meta_envelope(matched_total=1, returned=1, latency_ms=1)
    out = append_meta("body text", meta)
    assert out == "body text\n\n" + meta


def test_append_meta_empty_body() -> None:
    """Case 13: empty body → '\\n\\n_meta: {...}' (regex still matches at EOS)."""
    meta = meta_envelope(matched_total=0, returned=0, latency_ms=1)
    out = append_meta("", meta)
    assert out == "\n\n" + meta
    # Assembler-side regex matches at end of string
    tail_rx = re.compile(r"\n\n_meta: (\{.*\})$")
    assert tail_rx.search(out) is not None


# ---------------------------------------------------------------------------
#  Wire-shape regex contract — parametric over optional-field combinations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        # 1: required only
        {"matched_total": 0, "returned": 0, "latency_ms": 0},
        # 2: with filtered_by
        {
            "matched_total": 5,
            "returned": 3,
            "latency_ms": 12,
            "filtered_by": ["a", "b"],
        },
        # 3: with redactions
        {
            "matched_total": 5,
            "returned": 5,
            "latency_ms": 12,
            "redactions": ["pii"],
        },
        # 4: with next_cursor populated (string)
        {
            "matched_total": 100,
            "returned": 20,
            "latency_ms": 50,
            "next_cursor": "page-2",
        },
        # 5: with error_notes
        {
            "matched_total": 1,
            "returned": 1,
            "latency_ms": 1,
            "error_notes": ["partial-failure"],
        },
        # 6: with domain_hints
        {
            "matched_total": 1,
            "returned": 1,
            "latency_ms": 1,
            "domain_hints": {"r1": "family"},
        },
        # 7: every read-tier field populated
        {
            "matched_total": 9,
            "returned": 9,
            "latency_ms": 99,
            "filtered_by": ["x"],
            "redactions": ["y"],
            "next_cursor": "z",
            "error_notes": ["w"],
            "domain_hints": {"r": "d"},
        },
    ],
)
def test_envelope_regex_contract(kwargs: dict[str, object]) -> None:
    """Case 14: every meta_envelope(...) output matches ENVELOPE_RX."""
    line = meta_envelope(**kwargs)  # type: ignore[arg-type]
    assert ENVELOPE_RX.match(line) is not None
    # And the captured group is valid JSON
    m = ENVELOPE_RX.match(line)
    assert m is not None
    json.loads(m.group(1))  # must not raise


# ---------------------------------------------------------------------------
#  next_cursor explicit-string presence (covers the next_cursor != None branch
#  via append-shape verification)
# ---------------------------------------------------------------------------


def test_next_cursor_populated() -> None:
    """next_cursor='page-2' → present as JSON string value."""
    line = meta_envelope(matched_total=20, returned=10, latency_ms=5, next_cursor="page-2")
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["next_cursor"] == "page-2"


# ===========================================================================
#  DD-338 Phase D.1 — write-tier additive extension (v0.3.0)
# ===========================================================================


# ---------------------------------------------------------------------------
#  Relaxed-required: matched_total / returned now omit-when-None
# ---------------------------------------------------------------------------


def test_matched_total_omitted_when_none() -> None:
    """matched_total absent from kwargs → key absent from output (v0.3.0 relax)."""
    line = meta_envelope(latency_ms=5)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "matched_total" not in payload
    assert "returned" not in payload


def test_matched_total_explicit_none_omitted() -> None:
    """matched_total=None explicit → key absent (same as absent kwarg)."""
    line = meta_envelope(matched_total=None, returned=None, latency_ms=5)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "matched_total" not in payload
    assert "returned" not in payload


def test_latency_ms_always_present() -> None:
    """latency_ms is always present — only required field after v0.3.0 relax."""
    line = meta_envelope(latency_ms=0)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["latency_ms"] == 0
    # filtered_by / redactions / next_cursor still always present
    assert payload["filtered_by"] == []
    assert payload["redactions"] == []
    assert payload["next_cursor"] is None


# ---------------------------------------------------------------------------
#  rows_affected — write-tier
# ---------------------------------------------------------------------------


def test_rows_affected_none_omitted() -> None:
    """rows_affected=None → key absent."""
    line = meta_envelope(latency_ms=5, rows_affected=None)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "rows_affected" not in payload


def test_rows_affected_populated() -> None:
    """rows_affected=1 → key present as integer."""
    line = meta_envelope(latency_ms=5, rows_affected=1)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["rows_affected"] == 1


def test_rows_affected_zero_present() -> None:
    """rows_affected=0 → key present (0 is a meaningful write-tier value)."""
    line = meta_envelope(latency_ms=5, rows_affected=0)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["rows_affected"] == 0


# ---------------------------------------------------------------------------
#  target_id — write-tier
# ---------------------------------------------------------------------------


def test_target_id_none_omitted() -> None:
    """target_id=None → key absent."""
    line = meta_envelope(latency_ms=5, target_id=None)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "target_id" not in payload


def test_target_id_populated() -> None:
    """target_id='zone-123' → key present as string."""
    line = meta_envelope(latency_ms=5, target_id="zone-123")
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["target_id"] == "zone-123"


# ---------------------------------------------------------------------------
#  write_durability — write-tier
# ---------------------------------------------------------------------------


def test_write_durability_none_omitted() -> None:
    """write_durability=None → key absent."""
    line = meta_envelope(latency_ms=5, write_durability=None)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "write_durability" not in payload


@pytest.mark.parametrize("value", ["edge", "central", "replicated"])
def test_write_durability_canonical_values(value: str) -> None:
    """write_durability accepts the three canonical durability tiers."""
    line = meta_envelope(latency_ms=5, write_durability=value)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["write_durability"] == value


def test_write_durability_accepts_arbitrary_string() -> None:
    """write_durability does not enforce enum at helper layer — any string OK."""
    line = meta_envelope(latency_ms=5, write_durability="custom-tier-x")
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["write_durability"] == "custom-tier-x"


# ---------------------------------------------------------------------------
#  response_timestamp — write-tier
# ---------------------------------------------------------------------------


def test_response_timestamp_none_omitted() -> None:
    """response_timestamp=None → key absent."""
    line = meta_envelope(latency_ms=5, response_timestamp=None)
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert "response_timestamp" not in payload


def test_response_timestamp_populated() -> None:
    """response_timestamp ISO8601 → key present as string."""
    line = meta_envelope(latency_ms=5, response_timestamp="2026-05-24T12:34:56Z")
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload["response_timestamp"] == "2026-05-24T12:34:56Z"


# ---------------------------------------------------------------------------
#  Canonical key order — the byte-parity invariant
# ---------------------------------------------------------------------------


def test_canonical_key_order_kitchen_sink() -> None:
    """Kitchen sink: every field populated → keys appear in canonical order.

    Verifies that hand-assembled JSON respects:
        matched_total, returned, filtered_by, latency_ms, redactions,
        next_cursor, rows_affected, target_id, write_durability,
        response_timestamp, error_notes, domain_hints
    """
    line = meta_envelope(
        matched_total=10,
        returned=5,
        filtered_by=["scope=work"],
        latency_ms=42,
        redactions=["pii"],
        next_cursor="page-2",
        rows_affected=1,
        target_id="zone-abc",
        write_durability="central",
        response_timestamp="2026-05-24T12:00:00Z",
        error_notes=["warn-1"],
        domain_hints={"r1": "work"},
    )
    body = line[len("_meta: ") :]
    # Find the index of each key's quoted form in the raw JSON body.
    expected_order = [
        '"matched_total"',
        '"returned"',
        '"filtered_by"',
        '"latency_ms"',
        '"redactions"',
        '"next_cursor"',
        '"rows_affected"',
        '"target_id"',
        '"write_durability"',
        '"response_timestamp"',
        '"error_notes"',
        '"domain_hints"',
    ]
    indices = [body.index(k) for k in expected_order]
    # Indices must be strictly increasing.
    assert indices == sorted(indices), (
        "keys out of canonical order: "
        f"{list(zip(expected_order, indices, strict=True))}"
    )
    # Spot-check the literal prefix to nail the exact wire shape.
    expected_prefix = (
        '{"matched_total":10,"returned":5,"filtered_by":["scope=work"],'
        '"latency_ms":42,'
    )
    assert body.startswith(expected_prefix)


def test_canonical_key_order_write_tier_only() -> None:
    """Write-tier-only call: read-tier matched_total/returned omitted, write fields present."""
    line = meta_envelope(
        latency_ms=15,
        rows_affected=1,
        target_id="rec-789",
        write_durability="central",
        response_timestamp="2026-05-24T13:00:00+00:00",
    )
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    # Read-tier fields not in keys
    assert "matched_total" not in payload
    assert "returned" not in payload
    # Write-tier fields present
    assert payload["rows_affected"] == 1
    assert payload["target_id"] == "rec-789"
    assert payload["write_durability"] == "central"
    assert payload["response_timestamp"] == "2026-05-24T13:00:00+00:00"
    # Always-present fields still present
    assert payload["latency_ms"] == 15
    assert payload["filtered_by"] == []
    assert payload["redactions"] == []
    assert payload["next_cursor"] is None

    body = line[len("_meta: ") :]
    # Verify key order: filtered_by, latency_ms, redactions, next_cursor,
    # rows_affected, target_id, write_durability, response_timestamp.
    expected_order = [
        '"filtered_by"',
        '"latency_ms"',
        '"redactions"',
        '"next_cursor"',
        '"rows_affected"',
        '"target_id"',
        '"write_durability"',
        '"response_timestamp"',
    ]
    indices = [body.index(k) for k in expected_order]
    assert indices == sorted(indices)


def test_canonical_key_order_partial_write_tier() -> None:
    """Partial write-tier: only rows_affected + target_id present — order preserved."""
    line = meta_envelope(
        latency_ms=8,
        rows_affected=2,
        target_id="x",
    )
    body = line[len("_meta: ") :]
    # rows_affected must appear before target_id.
    assert body.index('"rows_affected"') < body.index('"target_id"')
    # write_durability + response_timestamp absent
    assert '"write_durability"' not in body
    assert '"response_timestamp"' not in body


# ---------------------------------------------------------------------------
#  Regex contract — extended for write-tier shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        # write-tier minimal
        {"latency_ms": 5, "rows_affected": 1},
        # write-tier full
        {
            "latency_ms": 5,
            "rows_affected": 0,
            "target_id": "abc",
            "write_durability": "edge",
            "response_timestamp": "2026-05-24T00:00:00Z",
        },
        # mixed read + write
        {
            "matched_total": 100,
            "returned": 50,
            "latency_ms": 99,
            "rows_affected": 1,
            "target_id": "id-1",
            "write_durability": "replicated",
            "response_timestamp": "2026-05-24T01:23:45+11:00",
            "error_notes": ["soft-warn"],
            "domain_hints": {"r": "d"},
        },
        # latency_ms only — minimal-valid envelope
        {"latency_ms": 0},
    ],
)
def test_write_tier_envelope_regex_contract(kwargs: dict[str, object]) -> None:
    """Write-tier shapes still satisfy the assembler-side regex contract."""
    line = meta_envelope(**kwargs)  # type: ignore[arg-type]
    assert ENVELOPE_RX.match(line) is not None
    # And captured payload parses as JSON.
    m = ENVELOPE_RX.match(line)
    assert m is not None
    json.loads(m.group(1))  # must not raise
    # Verify the tail regex used by assemblers also matches when appended.
    out = append_meta("body", line)
    tail_rx = re.compile(r"\n\n_meta: (\{.*\})$")
    assert tail_rx.search(out) is not None


# ---------------------------------------------------------------------------
#  Backwards compatibility — old-style call still works unchanged
# ---------------------------------------------------------------------------


def test_backwards_compat_old_style_call() -> None:
    """Existing v0.2.0 callers: matched_total/returned/filtered_by required → still work."""
    line = meta_envelope(
        matched_total=10,
        returned=5,
        filtered_by=["scope=work"],
        latency_ms=42,
        redactions=[],
    )
    payload = json.loads(ENVELOPE_RX.match(line).group(1))  # type: ignore[union-attr]
    assert payload == {
        "matched_total": 10,
        "returned": 5,
        "filtered_by": ["scope=work"],
        "latency_ms": 42,
        "redactions": [],
        "next_cursor": None,
    }
