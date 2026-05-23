"""Tests for ``stallari_mcp_helpers.audit_envelope``.

Coverage target: 100% line + branch on ``audit_envelope.py``.
Spec: ``2026-05-24-dd-338-e-python-mcp-helpers-package.md`` § Test Coverage.
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
        # 7: every field populated
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
