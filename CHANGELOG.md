# Changelog

All notable changes to `stallari-mcp-helpers` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-24

Initial release.

### Added
- `stallari_mcp_helpers.audit_envelope` module — canonical `meta_envelope(...)` builder and `append_meta(...)` joiner for the `_meta: {...}` JSON-tail block specified by DD-338 Phase A.1 wire contract. Locked encoding: tight JSON separators (`","`, `":"`); alphabetically-sorted `filtered_by`; `ensure_ascii=False` for Unicode preservation; required fields always present; optional fields omitted when None/empty per DD-338 DEVFU `2026-05-23-granularity-doc-optional-envelope-fields`.
- `stallari_mcp_helpers.domain_hint` module — `Pattern` dataclass + `compute_domain_hint(record, patterns)` first-match-wins attribution + `load_patterns_from_yaml(yaml_str)` config loader for per-record domain attribution per DD-338 A.2.dom.

### Motivation
- Per DD-338 Phase E.python (architect amendment 2026-05-23, substrate-corrected 2026-05-24) — eliminates 5× domain_hint duplication + 7× `_meta`-envelope helper duplication across first-party Stallari Python MCP servers (`gmail-blade-mcp`, `home-assistant-blade-mcp`, `mastodon-blade-mcp`, `tailscale-blade-mcp`, `syncthing-blade-mcp`, `caldav-blade-mcp`, `fastmail-blade-mcp`).
- Replaces the pre-consolidation pattern where each Python MCP carried its own copy of these helpers with mid-flight drift (5 different `_meta`-builder function-name pairs, mixed JSON separators, inconsistent `filtered_by` sort behaviour).

### Notes
- Public API frozen during `0.x` series only against breaking changes within a minor; subject to refinement until `1.0.0`.
- See [DD-338](https://github.com/Groupthink-dev) for the design record.
