"""Per-record domain-hint attribution engine.

First-match-wins pattern engine used by Stallari-conformant MCP servers to
annotate per-record results with a ``domain_hints: {record_id: domain}`` entry
in the ``_meta`` audit envelope.

Patterns live in user-authored config (typically a YAML file under a per-blade
state directory) and are loaded by the host MCP via :func:`load_patterns_from_yaml`.
The YAML shape::

    patterns:
      - field: from
        op: contains
        value: "@family.com"
        domain: family
      - field: labels.priority
        op: equals
        value: high
        domain: work

Fields are resolved against the record using dot-path navigation
(``labels.priority`` reads ``record["labels"]["priority"]``). Missing,
malformed, or empty config returns an empty pattern list — no ``domain_hints``
key is emitted (Convention #22 graceful degradation).
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pattern:
    """A single domain-hint matching rule.

    Attributes:
        field: Logical field name; resolved via dot-path navigation against
            the record (e.g. ``from`` reads ``record["from"]``;
            ``labels.priority`` reads ``record["labels"]["priority"]``).
        op: One of ``equals`` | ``contains`` | ``glob``. Unknown ops are
            silently skipped (defensive against future schema drift).
        value: Comparison value (always coerced to string; lists are matched
            element-wise).
        domain: Domain string to emit on match (e.g. ``family``, ``work``).
    """

    field: str
    op: Literal["equals", "contains", "glob"]
    value: str
    domain: str


_VALID_OPS = frozenset({"equals", "contains", "glob"})


def _resolve_dot_path(record: dict[str, Any], field: str) -> Any:
    """Resolve a dot-path field reference against a record.

    Returns ``None`` if any segment is missing or a non-final segment is not
    a mapping. The terminal segment may be any value, including ``None``.
    """
    cur: Any = record
    for segment in field.split("."):
        if not isinstance(cur, dict):
            return None
        if segment not in cur:
            return None
        cur = cur[segment]
    return cur


def compute_domain_hint(
    record: dict[str, Any],
    patterns: list[Pattern],
) -> str | None:
    """Compute the domain hint for a single record.

    First-match-wins over ``patterns``. Returns ``None`` when no pattern
    matches, the record lacks the resolved field, or the pattern list is
    empty.

    Fields are resolved by dot-path navigation
    (see :func:`_resolve_dot_path`). The resolved value may be:

        - ``None`` (field absent ⇒ no match)
        - a scalar (compared directly, coerced to ``str``)
        - a list of scalars or dicts (each element compared; dicts are
          coerced to empty string and skipped unless ``value=""``)

    Unknown ops are silently skipped — defensive against hand-authored
    config that may carry a future-schema op string.
    """
    if not patterns:
        return None
    for pattern in patterns:
        if pattern.op not in _VALID_OPS:
            continue
        rec_val = _resolve_dot_path(record, pattern.field)
        if rec_val is None:
            continue
        candidates: list[Any] = rec_val if isinstance(rec_val, list) else [rec_val]
        for c in candidates:
            if isinstance(c, dict):
                continue
            s = str(c)
            if pattern.op == "equals":
                if s == pattern.value:
                    return pattern.domain
            elif pattern.op == "contains":
                if pattern.value in s:
                    return pattern.domain
            else:  # pattern.op == "glob" — guarded by _VALID_OPS above
                if fnmatch.fnmatchcase(s, pattern.value):
                    return pattern.domain
    return None


def load_patterns_from_yaml(yaml_str: str) -> list[Pattern]:
    """Parse a YAML config string into a list of :class:`Pattern`.

    Returns ``[]`` on any of:

        - empty / whitespace-only input
        - YAML parse error (e.g. unterminated string)
        - non-mapping root
        - ``patterns`` key missing or non-list
        - per-pattern missing required keys or type errors

    Per-pattern parse failures are silently skipped (not fatal) — partial
    configs still load their good entries. This is Convention #22 graceful
    degradation: hand-authored config never crashes the host MCP.
    """
    if not yaml_str.strip():
        return []
    try:
        import yaml
    except ImportError:
        logger.warning("pyyaml not installed; domain_hint patterns disabled")
        return []
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        logger.warning("domain-hint YAML parse error: %s", e)
        return []
    if not data or not isinstance(data, dict):
        return []
    raw_patterns = data.get("patterns", [])
    if not isinstance(raw_patterns, list):
        return []
    result: list[Pattern] = []
    for p in raw_patterns:
        if not isinstance(p, dict):
            continue
        try:
            result.append(
                Pattern(
                    field=str(p["field"]),
                    op=str(p["op"]),  # type: ignore[arg-type]
                    value=str(p["value"]),
                    domain=str(p["domain"]),
                )
            )
        except (KeyError, TypeError):
            continue
    return result
