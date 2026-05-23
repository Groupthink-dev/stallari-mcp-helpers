"""Tests for ``stallari_mcp_helpers.domain_hint``.

Coverage target: 100% line + branch on ``domain_hint.py``.
Spec: ``2026-05-24-dd-338-e-python-mcp-helpers-package.md`` § Test Coverage.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from stallari_mcp_helpers.domain_hint import (
    Pattern,
    compute_domain_hint,
    load_patterns_from_yaml,
)

# ---------------------------------------------------------------------------
#  compute_domain_hint
# ---------------------------------------------------------------------------


def test_empty_patterns_returns_none() -> None:
    """Case 1: empty patterns list → None."""
    assert compute_domain_hint({"from": "alice@example.com"}, []) is None


def test_equals_match_top_level_field() -> None:
    """Case 2: single equals-match on top-level field → matched domain."""
    patterns = [Pattern(field="from", op="equals", value="alice@example.com", domain="work")]
    assert compute_domain_hint({"from": "alice@example.com"}, patterns) == "work"


def test_contains_match_string_field() -> None:
    """Case 3: single contains-match on string field → matched domain."""
    patterns = [Pattern(field="from", op="contains", value="@family.com", domain="family")]
    assert compute_domain_hint({"from": "bob@family.com"}, patterns) == "family"


def test_glob_match_string_field() -> None:
    """Case 4: single glob-match on string field → matched domain."""
    patterns = [Pattern(field="from", op="glob", value="*@family.com", domain="family")]
    assert compute_domain_hint({"from": "alice@family.com"}, patterns) == "family"


def test_first_match_wins() -> None:
    """Case 5: two patterns match same record → first pattern's domain."""
    patterns = [
        Pattern(field="from", op="contains", value="@example.com", domain="first"),
        Pattern(field="from", op="contains", value="alice", domain="second"),
    ]
    assert compute_domain_hint({"from": "alice@example.com"}, patterns) == "first"


def test_unknown_op_never_matches() -> None:
    """Case 6: unknown op → never-matches (returns None)."""
    patterns = [Pattern(field="from", op="regex", value="alice", domain="work")]
    assert compute_domain_hint({"from": "alice@example.com"}, patterns) is None


def test_missing_field_no_match() -> None:
    """Case 7: pattern targets missing field → no match."""
    patterns = [Pattern(field="to", op="equals", value="alice", domain="work")]
    assert compute_domain_hint({"from": "alice@example.com"}, patterns) is None


def test_nested_dot_path_match() -> None:
    """Case 8: pattern targets nested field via dot-path → matched domain."""
    patterns = [
        Pattern(field="labels.priority", op="equals", value="high", domain="urgent"),
    ]
    record = {"labels": {"priority": "high"}}
    assert compute_domain_hint(record, patterns) == "urgent"


def test_list_field_element_wise_match() -> None:
    """List-valued field: each element compared; any element match wins."""
    patterns = [Pattern(field="labelIds", op="equals", value="Label_42", domain="work")]
    record = {"labelIds": ["Label_1", "Label_42", "Label_99"]}
    assert compute_domain_hint(record, patterns) == "work"


def test_list_with_dict_elements_skipped() -> None:
    """Dict elements in a list-valued field are skipped (cannot be matched)."""
    patterns = [Pattern(field="headers", op="equals", value="x", domain="d")]
    record = {"headers": [{"name": "From"}, {"name": "To"}]}
    assert compute_domain_hint(record, patterns) is None


def test_dot_path_through_non_dict_returns_none() -> None:
    """Dot-path segments through a non-dict intermediate → no match."""
    patterns = [Pattern(field="labels.priority.score", op="equals", value="9", domain="d")]
    record = {"labels": {"priority": "high"}}  # priority is str, not dict
    assert compute_domain_hint(record, patterns) is None


def test_value_coercion_to_str() -> None:
    """Non-string scalar field values are coerced to str for comparison."""
    patterns = [Pattern(field="priority", op="equals", value="42", domain="d")]
    assert compute_domain_hint({"priority": 42}, patterns) == "d"


def test_glob_no_match_falls_through_to_next_candidate() -> None:
    """Glob op evaluated but no match → iteration continues past the candidate."""
    patterns = [Pattern(field="labelIds", op="glob", value="Label_4*", domain="work")]
    record = {"labelIds": ["Label_1", "Label_42"]}
    # First candidate doesn't match (fall through 118->107), second does.
    assert compute_domain_hint(record, patterns) == "work"


def test_glob_no_match_at_all_returns_none() -> None:
    """All candidates fall through every op branch with no match → None."""
    patterns = [Pattern(field="from", op="glob", value="*@example.com", domain="d")]
    assert compute_domain_hint({"from": "alice@other.org"}, patterns) is None


# ---------------------------------------------------------------------------
#  load_patterns_from_yaml
# ---------------------------------------------------------------------------


def test_load_empty_string_returns_empty_list() -> None:
    """Case 9: load_patterns_from_yaml('') → []."""
    assert load_patterns_from_yaml("") == []


def test_load_malformed_yaml_returns_empty_list() -> None:
    """Case 10: malformed YAML (unterminated string) → [] (no raise)."""
    assert load_patterns_from_yaml('patterns:\n  - field: "unterminated\n') == []


def test_load_valid_patterns_block() -> None:
    """Case 11: valid patterns block → list of Pattern with correct fields."""
    yaml_str = """
patterns:
  - field: from
    op: contains
    value: "@family.com"
    domain: family
  - field: labelIds
    op: equals
    value: Label_42
    domain: work
"""
    result = load_patterns_from_yaml(yaml_str)
    assert len(result) == 2
    assert result[0] == Pattern(field="from", op="contains", value="@family.com", domain="family")
    assert result[1] == Pattern(field="labelIds", op="equals", value="Label_42", domain="work")


def test_load_pattern_with_missing_required_field_skipped() -> None:
    """Case 12: pattern entry missing required field → entry skipped; rest returned."""
    yaml_str = """
patterns:
  - field: from
    op: contains
    value: "@example.com"
    # domain missing
  - field: from
    op: equals
    value: alice@example.com
    domain: work
"""
    result = load_patterns_from_yaml(yaml_str)
    assert len(result) == 1
    assert result[0].domain == "work"


def test_load_whitespace_only_yaml_returns_empty_list() -> None:
    """Case 13: whitespace-only YAML → []."""
    assert load_patterns_from_yaml("   \n  \t\n") == []


def test_load_yaml_missing_patterns_key_returns_empty_list() -> None:
    """Case 14: YAML with patterns key missing entirely → []."""
    assert load_patterns_from_yaml("other_key: value") == []


def test_compute_per_record_aggregates_to_id_map() -> None:
    """Case 15: compute_domain_hint applied per-record → aggregable map."""
    patterns = [
        Pattern(field="from", op="contains", value="@family.com", domain="family"),
        Pattern(field="from", op="contains", value="@example.com", domain="work"),
    ]
    records = [
        {"id": "r1", "from": "alice@family.com"},
        {"id": "r2", "from": "bob@example.com"},
        {"id": "r3", "from": "carol@other.org"},
    ]
    result = {r["id"]: compute_domain_hint(r, patterns) for r in records}
    assert result == {"r1": "family", "r2": "work", "r3": None}


# ---------------------------------------------------------------------------
#  Branch-coverage extras (defensive / structural paths)
# ---------------------------------------------------------------------------


def test_load_non_mapping_root_returns_empty_list() -> None:
    """YAML root is a list, not a mapping → []."""
    assert load_patterns_from_yaml("- one\n- two\n") == []


def test_load_patterns_key_not_a_list_returns_empty_list() -> None:
    """patterns: scalar (not a list) → []."""
    assert load_patterns_from_yaml("patterns: not-a-list") == []


def test_load_patterns_entry_not_a_dict_skipped() -> None:
    """A non-dict entry inside patterns: list is silently skipped."""
    yaml_str = """
patterns:
  - "bare string entry"
  - field: from
    op: equals
    value: x
    domain: d
"""
    result = load_patterns_from_yaml(yaml_str)
    assert len(result) == 1
    assert result[0].field == "from"


def test_load_null_root_returns_empty_list() -> None:
    """YAML parses to None (e.g. a comment-only doc) → []."""
    assert load_patterns_from_yaml("# just a comment\n") == []


def test_load_yaml_warns_on_parse_error(caplog: pytest.LogCaptureFixture) -> None:
    """Malformed YAML logs a warning."""
    with caplog.at_level(logging.WARNING, logger="stallari_mcp_helpers.domain_hint"):
        load_patterns_from_yaml('patterns:\n  - "unterminated\n')
    assert any("YAML parse error" in r.message for r in caplog.records)


def test_load_yaml_missing_pyyaml(caplog: pytest.LogCaptureFixture) -> None:
    """pyyaml ImportError path returns [] and logs a warning."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "yaml":
            raise ImportError("simulated missing pyyaml")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger="stallari_mcp_helpers.domain_hint"):
        with patch.object(builtins, "__import__", side_effect=fake_import):
            result = load_patterns_from_yaml("patterns:\n  - field: x\n")
    assert result == []
    assert any("pyyaml not installed" in r.message for r in caplog.records)


def test_pattern_is_frozen() -> None:
    """Pattern is a frozen dataclass — attribute assignment raises."""
    p = Pattern(field="from", op="equals", value="x", domain="d")
    with pytest.raises((AttributeError, Exception)):
        p.field = "to"  # type: ignore[misc]
