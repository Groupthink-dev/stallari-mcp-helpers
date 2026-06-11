"""Cross-language golden parity fixture (AUD-04-12).

The byte string below is the locked v0.4.0 wire contract. The identical
literal is asserted in the TypeScript (`tests/parity-golden.test.ts`) and
Swift (`Tests/MCPHelpersTests/ParityGoldenTests.swift`) sibling repos —
all three helpers MUST render these exact bytes for the same input.

The fixture is deliberately collation-hostile: ``\N{REPLACEMENT CHARACTER}b``
(U+FFFD) must sort BEFORE ``\N{GRINNING FACE}a`` (U+1F600) — true under
Unicode code-point order (the locked collation), false under JS's default
UTF-16 code-unit sort and unverified under Swift's default
Unicode-canonical ``String <``. ``domain_hints`` keys are passed in
non-sorted insertion order to pin the v0.4.0 key-sort behaviour.
"""

from __future__ import annotations

from stallari_mcp_helpers.audit_envelope import append_meta, meta_envelope

GOLDEN_FULL = (
    '_meta: {"matched_total":42,"returned":10,'
    '"filtered_by":["Alpha","a/b","zeta","émile","�b","\U0001f600a"],'
    '"latency_ms":7,"redactions":["token"],"next_cursor":"abc/def",'
    '"rows_affected":3,"target_id":"t-1","write_durability":"edge",'
    '"response_timestamp":"2026-06-12T00:00:00+10:00",'
    '"error_notes":["note"],'
    '"domain_hints":{"r1":"family","r2":"work","ré":"home"}}'
)

GOLDEN_WRITE_MINIMAL = (
    '_meta: {"filtered_by":[],"latency_ms":1,"redactions":[],'
    '"next_cursor":null,"rows_affected":1,"target_id":"x",'
    '"write_durability":"edge"}'
)


def test_golden_full_envelope() -> None:
    line = meta_envelope(
        latency_ms=7,
        matched_total=42,
        returned=10,
        filtered_by=["zeta", "Alpha", "émile", "\U0001f600a", "�b", "a/b"],
        redactions=["token"],
        next_cursor="abc/def",
        rows_affected=3,
        target_id="t-1",
        write_durability="edge",
        response_timestamp="2026-06-12T00:00:00+10:00",
        error_notes=["note"],
        domain_hints={"r2": "work", "r1": "family", "ré": "home"},
    )
    assert line == GOLDEN_FULL


def test_golden_write_minimal_envelope() -> None:
    line = meta_envelope(latency_ms=1, rows_affected=1, target_id="x", write_durability="edge")
    assert line == GOLDEN_WRITE_MINIMAL


def test_append_meta_joiner() -> None:
    assert append_meta("body", GOLDEN_WRITE_MINIMAL) == ("body\n\n" + GOLDEN_WRITE_MINIMAL)
