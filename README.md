# stallari-mcp-helpers

Canonical helpers for Python MCP servers targeting **Stallari**'s contract surface — a tight library that lets your tools emit the audit envelope and per-record domain attribution the Stallari assembler expects, without you rolling your own.

If you're porting a Python MCP server to Stallari and want first-party-tier conformance, this is the on-ramp.

## About Stallari

Stallari is an agentic personal-knowledge-management platform. It runs [MCP servers](https://modelcontextprotocol.io) as its tool surface — the way it talks to email providers, calendars, smart-home hubs, source control, cloud infra, etc. Your MCP server dispatches through Stallari's assembler, which audits each tool call against a wire-shape contract before lifting the result into the LLM's context. This package provides the canonical helpers that make a Python MCP server emit that contract cleanly.

## Sister packages

| Language | Package | Source |
|---|---|---|
| **Python** | [`stallari-mcp-helpers` on PyPI](https://pypi.org/project/stallari-mcp-helpers/) | this repo |
| **TypeScript** | [`stallari-mcp-helpers` on npm](https://www.npmjs.com/package/stallari-mcp-helpers) | [`stallari-mcp-helpers-ts`](https://github.com/Groupthink-dev/stallari-mcp-helpers-ts) |
| **Swift** | `MCPHelpers` via Swift Package Manager | [`stallari-mcp-helpers-swift`](https://github.com/Groupthink-dev/stallari-mcp-helpers-swift) |

All three packages stay in lockstep on the wire shape — `meta_envelope(...)` in Python, `formatMetaLine(...)` in TypeScript, and `formatMetaLine(...)` in Swift all emit byte-equivalent `_meta` envelopes for the same input.

## What this is

Two small modules:

- **`audit_envelope`** — renders the canonical `_meta: {...}` JSON-tail block the Stallari assembler lifts into its `ContextPacket.provenance` audit trail. Locked encoding: tight JSON separators, alphabetically-sorted `filtered_by`, Unicode preserved, required/optional field discipline matching the DD-338 wire contract.
- **`domain_hint`** — pattern engine for per-record domain attribution when your tool spans multiple user-defined domains (e.g. a Gmail account that mixes `work-acme` and `personal`). Users author YAML rules in `<state-root>/blade-config/<your-mcp>/config.yaml`; your tool loads them once, calls `compute_domain_hint(record, patterns)` per record, and folds the result into `_meta.domain_hints`.

This package does **not** ship MCP-server scaffolding, tool registration, HTTP/IPC, inference, or stable-ordering primitives. It's deliberately small.

## Audience

Direct consumers today:

- **First-party Stallari Python MCP servers** — `gmail-blade-mcp`, `home-assistant-blade-mcp`, `mastodon-blade-mcp`, `tailscale-blade-mcp`, `syncthing-blade-mcp`, `caldav-blade-mcp`, `fastmail-blade-mcp`. (These previously each carried their own copy of `domain_hint.py` + their own `_meta`-envelope helper; this package eliminates the duplication.)

Broader audience:

- **Any Python MCP author** who wants their server to dispatch through Stallari at first-party-tier conformance. You don't have to be on the Stallari team. Add the dep, use the helpers, declare your tool capabilities honestly in your pack manifest, and the assembler will treat your tool as a first-class participant.

If you're integrating a third-party MCP that you don't control, the Stallari adapter-transform layer (deterministic YAML, in-process) handles you separately — you don't need this library. See the Stallari docs for adapter-transform virtualisation if that's your path.

## Install

```bash
uv add stallari-mcp-helpers
# or
pip install stallari-mcp-helpers
```

## Quick start — emitting a `_meta` envelope

```python
from stallari_mcp_helpers import meta_envelope, append_meta

def my_search_tool(query: str, scope: str = "personal") -> str:
    records = upstream_api.search(query, filter=f"scope={scope}")
    body = format_records(records)

    meta = meta_envelope(
        matched_total=records.total_matched,
        returned=len(records.items),
        latency_ms=records.latency_ms,
        filtered_by=[f"scope={scope}", f"query={query}"],
        # required fields:
        redactions=[],
        next_cursor=None,
        # optional — omit when None/empty:
        error_notes=None,
        domain_hints=None,
    )
    return append_meta(body, meta)
```

Output (assembler-side regex contract: `\n\n_meta: (\{.*\})$`):

```
<your body>

_meta: {"matched_total":42,"returned":10,"latency_ms":234,"filtered_by":["query=foo","scope=personal"],"redactions":[],"next_cursor":null}
```

## Quick start — per-record domain attribution

User authors `<state-root>/blade-config/<your-mcp>/config.yaml`:

```yaml
patterns:
  - field: from
    op: contains
    value: "@acme.com"
    domain: work-acme
  - field: labelIds
    op: equals
    value: Label_42
    domain: personal
```

Your tool loads it once at startup:

```python
from pathlib import Path
from stallari_mcp_helpers import load_patterns_from_yaml, compute_domain_hint, meta_envelope, append_meta

_PATTERNS_PATH = Path.home() / ".local/state/stallari/blade-config/my-mcp/config.yaml"

def _load_patterns():
    try:
        return load_patterns_from_yaml(_PATTERNS_PATH.read_text())
    except (FileNotFoundError, OSError):
        return []  # graceful degradation — Convention #22

_patterns = _load_patterns()
```

Then per request:

```python
def my_list_tool() -> str:
    records = upstream_api.list()
    domain_hints = {
        r.id: hint
        for r in records
        if (hint := compute_domain_hint(r.to_dict(), _patterns)) is not None
    }
    meta = meta_envelope(
        matched_total=len(records),
        returned=len(records),
        latency_ms=elapsed,
        filtered_by=[],
        redactions=[],
        next_cursor=None,
        domain_hints=domain_hints or None,  # omitted when empty
    )
    return append_meta(format_records(records), meta)
```

## Manifest declarations you'll make

Per tool in your pack catalog entry:

```json
{
  "name": "my_search_tool",
  "granularity": {
    "scope_filtering": "server-side",
    "deterministic_ordering": "stable",
    "audit_surface": "structured",
    "domain_scope": "multi"
  }
}
```

Four honest declarations. If you implement `scope_filtering: server-side` you must actually filter at the upstream API (not in your code post-fetch). If you declare `deterministic_ordering: stable` your output must be reproducible. If you declare `audit_surface: structured` your tool must emit `meta_envelope(...)` on every call. If you declare `domain_scope: multi` your tool must emit per-record `domain_hints` when configured.

Stallari's conformance harness verifies these claims against your actual tool behaviour at pack-acceptance time. Honest degraded declarations always pass; lying about a capability fails. Start with the most conservative declarations and bump each axis as you implement the corresponding behaviour.

## What you don't have to think about

- Exact JSON encoding of `_meta` envelopes (separator choice, sort order, Unicode handling)
- How to handle `domain_hints` when no patterns match
- Graceful degradation on missing config files
- The assembler-side `ContextPacket` shape that consumes your envelopes
- Future contract evolution — the library version-pins the wire shape

All of that lives here. You write your tool, declare your contract honestly, and the rest is plumbing.

## API reference

### `audit_envelope`

```python
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
    """Render the canonical `_meta: {...}` JSON-tail envelope line."""

def append_meta(body: str, meta_line: str) -> str:
    """Append a `_meta: {...}` line to a tool's body with `\\n\\n` joiner."""
```

### `domain_hint`

```python
@dataclass(frozen=True)
class Pattern:
    field: str
    op: Literal["equals", "contains", "glob"]
    value: str
    domain: str

def compute_domain_hint(
    record: dict[str, Any],
    patterns: list[Pattern],
) -> str | None:
    """First-match-wins. Returns matched domain or None."""

def load_patterns_from_yaml(yaml_str: str) -> list[Pattern]:
    """Parse a `patterns:` YAML block. Malformed/empty returns []."""
```

## Versioning

SemVer. `0.x.y` series while the public API stabilises; `1.0.0` once consumers have shipped against `0.x` for >30 days with no API churn.

Breaking changes after `1.0.0` get a one-minor-version deprecation window (`v1.y` warns, `v2.0` removes).

## License

MIT. See `LICENSE`.

## Contributing

This is internal Stallari plumbing during the `0.x` series — issues + PRs accepted but the API surface is still settling. Submit issues at the [GitHub tracker](https://github.com/Groupthink-dev/stallari-mcp-helpers/issues).
