# Changelog

All notable changes to `stallari-mcp-helpers` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-24

### Added — DD-338 Phase D.1 MetaEnvelope additive extension for write-tier fields
- Four new optional **write-tier** fields on `meta_envelope(...)`, all omit-when-`None`:
  - `rows_affected: int | None` — count of rows/records affected by a write operation.
  - `target_id: str | None` — identifier of the write target (e.g. DNS record ID, R2 object key, KV key, vault note path).
  - `write_durability: str | None` — durability tier of the write. Canonical values: `"edge" | "central" | "replicated"`. No enum enforcement at the helper layer — any string is accepted to keep callable from upstream APIs whose vocabulary may extend.
  - `response_timestamp: str | None` — ISO8601 timestamp echoed from upstream API response (e.g. Cloudflare's `X-Response-Time`-style headers).
- **Canonical key order** locked across languages (TS + Swift sibling helpers v0.3.0). When present, keys appear in this exact order in the rendered JSON: `matched_total, returned, filtered_by, latency_ms, redactions, next_cursor, rows_affected, target_id, write_durability, response_timestamp, error_notes, domain_hints`. JSON is now hand-assembled rather than passed through a single `json.dumps(dict, ...)` call to guarantee byte-parity across Python / TypeScript / Swift implementations; per-value serialization still uses `json.dumps` with the locked separators + `ensure_ascii=False`.

### Changed
- `matched_total` and `returned` relaxed from required to optional (omit-when-`None`). Write-tier callers (creating/updating/deleting a single record) can now omit the read-tier counts that don't apply. `latency_ms` remains the only always-present field beyond `filtered_by` / `redactions` / `next_cursor` (which keep their present-with-default discipline).
- `meta_envelope(...)` signature: `latency_ms` is the first kwarg (still kwarg-only); `matched_total` and `returned` default to `None`; the four new write-tier kwargs default to `None`. The kwarg-only discipline from v0.1.0 is preserved so all existing call sites that pass `matched_total=…, returned=…, latency_ms=…` (with or without `filtered_by` / `redactions` / `next_cursor`) continue to work without modification.

### Backwards compatibility
- All 7 known Python consumer blade-mcps (gmail, home-assistant, mastodon, tailscale, syncthing, caldav, fastmail) continue to work without code changes. Existing v0.2.0 read-tier call shapes produce byte-identical output to v0.2.0 because the canonical key order matches the previous `dict` iteration order on CPython for the read-tier-only field set.
- The S-AUD-001 lint rule (`stallari_mcp_helpers.lint`) is unchanged in this release.

### Notes
- The canonical key order is a wire-contract invariant — re-ordering it is a breaking change requiring a major bump. The new write-tier keys are appended after the read-tier block and before `error_notes` / `domain_hints` to keep the read-tier prefix byte-identical with v0.2.0 output.
- `write_durability` is a string rather than an enum at the helper layer because individual blade-mcps may need to surface tier vocabulary specific to the upstream service (e.g. R2 has "eventually consistent" + "strongly consistent" reads but only one write tier; DNS has zone-level vs edge propagation distinctions). The catalog/conformance harness is the right place to enforce the canonical-three vocabulary; the helper layer stays permissive.

## [0.2.0] - 2026-05-24

### Added
- `stallari_mcp_helpers.lint` module — DD-338 Phase B Python implementation of the cross-language **S-AUD-001** audit-surface honesty lint rule.
- `lint_blade(blade_source_root, catalog_entry) -> LintResult` — static AST-based check that every tool declaring `granularity.audit_surface == "structured"` in the catalog has its function body invoke `append_meta` (directly, via re-export, via alias import, or via a wrapper function up to 3 hops deep). Companion to the runtime `LiveMCPToolProbe` in `stallari_capability_conformance.probe`; cheap to run in CI without spawning subprocesses or supplying credentials.
- `LintResult` dataclass with `to_dict()` rendering the per-tool verdict envelope that mirrors the live probe's sidecar JSON shape (same `audit_surface: { declared, actual, result, detail }` block, same summary counters), so a single rendering surface can consume both static and runtime verdicts uniformly.
- `stallari-mcp-lint` console script (`stallari_mcp_helpers.lint:_cli`) — argparse-driven CLI: `stallari-mcp-lint <source-root> --catalog <catalog.json> [--output <sidecar.json>] [--strict]`. `--strict` exits non-zero on any over-declared / under-declared verdict (indeterminate verdicts do not trip strict mode).

### Notes
- FastMCP decorator coverage: `@<mcp|server|app>.tool`, `@<mcp|server|app>.tool()`, `@<mcp|server|app>.tool(name="...")`, and `@<x>.tool(name="...", annotations={...})` are all detected. Imperative `server.add_tool(fn, name="...")` is NOT statically resolved — those tools surface as `indeterminate` rather than guessed.
- Smoke-verified clean against `syncthing-blade-mcp` (38 tools, 0 over-declared); reports 6 over-declared on `apple-messages-blade-mcp`, matching the Phase A static heuristic.

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
