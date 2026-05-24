# Changelog

All notable changes to `stallari-mcp-helpers` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-05-24

### Added
- `py.typed` marker file (PEP 561). Consumer mypy with `strict = true` + `warn_return_any = true` can now fully introspect the public-API annotations without `[[tool.mypy.overrides]] ignore_missing_imports = true` blocks or `cast()` workarounds at every return site.
- Motivation: discovered post-v0.1.0 release when 7 consumer blade-mcps (gmail, home-assistant, mastodon, tailscale, syncthing, caldav, fastmail) all independently needed mypy workarounds in their DD-338 Phase E.python flip PRs. v0.1.1 closes the gap so the follow-up cleanup sweep can remove those workarounds.

### Notes
- Pure metadata addition. No public API changes. No behavioural changes. Safe to upgrade without consumer changes; consumers benefit by removing workarounds at their own cadence.

## [0.1.0] - 2026-05-24

Initial release.

### Added
- `stallari_mcp_helpers.audit_envelope` module — canonical `meta_envelope(...)` builder and `append_meta(...)` joiner for the `_meta: {...}` JSON-tail block specified by DD-338 Phase A.1 wire contract. Locked encoding: tight JSON separators (`","`, `":"`); alphabetically-sorted `filtered_by`; `ensure_ascii=False` for Unicode preservation; required fields always present; optional fields omitted when None/empty per DD-338 DEVFU `2026-05-23-granularity-doc-optional-envelope-fields`.
- `stallari_mcp_helpers.domain_hint` module — `Pattern` dataclass + `compute_domain_hint(record, patterns)` first-match-wins attribution + `load_patterns_from_yaml(yaml_str)` config loader for per-record domain attribution per DD-338 A.2.dom.

#### Public API — `stallari_mcp_helpers.audit_envelope`

- `meta_envelope(*, matched_total: int, returned: int, latency_ms: int, filtered_by: list[str] | None = None, redactions: list[str] | None = None, next_cursor: str | None = None, error_notes: list[str] | None = None, domain_hints: dict[str, str] | None = None) -> str` — renders the canonical `_meta: {...}` JSON-tail line. Required fields (`matched_total`, `returned`, `latency_ms`, `filtered_by`, `redactions`, `next_cursor`) are always serialized; `filtered_by` and `redactions` default to `[]`; `next_cursor` defaults to JSON `null`. Optional fields (`error_notes`, `domain_hints`) are omitted entirely when `None` or empty per Convention #22. Kwarg-only signature.
- `append_meta(body: str, meta_line: str) -> str` — joins a body and a `_meta:` line with `\n\n`. Joiner is always two newlines regardless of body content; the assembler-side regex `r"\n\n_meta: (\{.*\})$"` matches at end-of-string in both empty- and non-empty-body cases.

#### Public API — `stallari_mcp_helpers.domain_hint`

- `class Pattern(field: str, op: Literal["equals", "contains", "glob"], value: str, domain: str)` — frozen dataclass; one attribution rule. `field` supports dot-path navigation (e.g. `labels.priority` reads `record["labels"]["priority"]`).
- `compute_domain_hint(record: dict[str, Any], patterns: list[Pattern]) -> str | None` — first-match-wins iteration over `patterns`. Returns the matched pattern's domain or `None` when no pattern matches, the resolved field is absent, or the pattern list is empty. Unknown ops are silently skipped (defensive against future schema drift). List-valued fields are matched element-wise; dict-valued list elements are skipped.
- `load_patterns_from_yaml(yaml_str: str) -> list[Pattern]` — parses a `patterns:` YAML block into a list of `Pattern`. Returns `[]` on empty/whitespace-only input, YAML parse error, non-mapping root, missing/non-list `patterns:` key, or `ImportError` when `pyyaml` is absent. Per-pattern parse failures (missing required keys, type errors) are silently skipped; partial configs still load good entries. Convention #22 graceful degradation throughout.

### Motivation
- Per DD-338 Phase E.python (architect amendment 2026-05-23, substrate-corrected 2026-05-24) — eliminates 5× domain_hint duplication + 7× `_meta`-envelope helper duplication across first-party Stallari Python MCP servers (`gmail-blade-mcp`, `home-assistant-blade-mcp`, `mastodon-blade-mcp`, `tailscale-blade-mcp`, `syncthing-blade-mcp`, `caldav-blade-mcp`, `fastmail-blade-mcp`).
- Replaces the pre-consolidation pattern where each Python MCP carried its own copy of these helpers with mid-flight drift (5 different `_meta`-builder function-name pairs, mixed JSON separators, inconsistent `filtered_by` sort behaviour).

### Notes
- Public API frozen during `0.x` series only against breaking changes within a minor; subject to refinement until `1.0.0`.
- The wire contract is specified by Stallari internal design record DD-338 (private; the public summary surfaces gradually as the contract stabilises).
