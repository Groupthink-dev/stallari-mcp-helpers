"""Tests for ``stallari_mcp_helpers.lint``.

Coverage target: 100% line + branch on ``lint.py`` for the verdict-producing
paths. Spec: ``2026-05-24-dd-338-b-python-lint-substrate.md`` § Test Coverage.

Each case constructs a tiny synthetic blade source tree under ``tmp_path``
plus a synthetic catalog entry, runs :func:`lint_blade`, and asserts the
verdict shape + counts. The synthesis pattern mirrors the real-world
FastMCP decorator + module layout (``server.py`` registers ``mcp`` and
re-exports occur via sibling modules).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stallari_mcp_helpers.lint import (
    CANONICAL_EMIT_NAME,
    LINT_RULE_ID,
    LintResult,
    _cli,
    lint_blade,
)

# ---------------------------------------------------------------------------
#  Helpers — synthetic blade-source builders
# ---------------------------------------------------------------------------


def _write_blade(
    root: Path,
    *,
    package: str,
    server_body: str,
    extra_modules: dict[str, str] | None = None,
) -> Path:
    """Materialise a synthetic blade source tree under ``root``.

    Returns the source root path that should be passed to ``lint_blade``
    (the directory directly containing the package — mirrors how the
    real-world ``src/<package>/`` layout is consumed).
    """
    pkg_dir = root / package
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "server.py").write_text(server_body, encoding="utf-8")
    for name, body in (extra_modules or {}).items():
        # Allow nested module paths like "tools/devices".
        target = pkg_dir / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent != pkg_dir and not (target.parent / "__init__.py").exists():
            (target.parent / "__init__.py").write_text("", encoding="utf-8")
        target.write_text(body, encoding="utf-8")
    return root


def _catalog(
    blade: str,
    tools: list[tuple[str, str]],
) -> dict:
    """Build a minimal catalog entry: ``[(tool_name, audit_surface), ...]``."""
    return {
        "name": blade,
        "tools": [
            {
                "name": name,
                "granularity": {"audit_surface": surface},
            }
            for name, surface in tools
        ],
    }


# ---------------------------------------------------------------------------
#  L1 — direct call pass
# ---------------------------------------------------------------------------


def test_l1_direct_call_pass(tmp_path: Path) -> None:
    """Tool calls append_meta directly; catalog declares structured → match."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_direct() -> str:
    body = "hi"
    return append_meta(body, meta_envelope(matched_total=1, returned=1, latency_ms=1))
"""
    root = _write_blade(tmp_path, package="bladeL1", server_body=server)
    result = lint_blade(root, _catalog("blade-l1", [("t_direct", "structured")]))
    verdict = result.tools["t_direct"]["audit_surface"]
    assert verdict["result"] == "match"
    assert verdict["actual"] == "structured"


# ---------------------------------------------------------------------------
#  L2 — direct call gap
# ---------------------------------------------------------------------------


def test_l2_direct_call_gap(tmp_path: Path) -> None:
    """Tool returns text without append_meta; catalog declares structured → over-declared."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_silent() -> str:
    return "no envelope here"
"""
    root = _write_blade(tmp_path, package="bladeL2", server_body=server)
    result = lint_blade(root, _catalog("blade-l2", [("t_silent", "structured")]))
    verdict = result.tools["t_silent"]["audit_surface"]
    assert verdict["result"] == "over-declared"
    assert verdict["actual"] == "minimal"


# ---------------------------------------------------------------------------
#  L3 — indirect via re-export
# ---------------------------------------------------------------------------


def test_l3_indirect_via_reexport(tmp_path: Path) -> None:
    """Tool imports append_meta from a sibling module that re-exports it."""
    server = """
from .formatters import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_reexport() -> str:
    return append_meta("body", meta_envelope(matched_total=1, returned=1, latency_ms=1))
"""
    formatters = """
from stallari_mcp_helpers import append_meta, meta_envelope
_ = (append_meta, meta_envelope)
"""
    root = _write_blade(
        tmp_path,
        package="bladeL3",
        server_body=server,
        extra_modules={"formatters": formatters},
    )
    result = lint_blade(root, _catalog("blade-l3", [("t_reexport", "structured")]))
    verdict = result.tools["t_reexport"]["audit_surface"]
    assert verdict["result"] == "match", verdict["detail"]


# ---------------------------------------------------------------------------
#  L4 — indirect via alias import
# ---------------------------------------------------------------------------


def test_l4_indirect_via_alias(tmp_path: Path) -> None:
    """Tool imports append_meta as _emit; calls _emit(...) → match."""
    server = """
from stallari_mcp_helpers import append_meta as _emit, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_aliased() -> str:
    return _emit("body", meta_envelope(matched_total=0, returned=0, latency_ms=0))
"""
    root = _write_blade(tmp_path, package="bladeL4", server_body=server)
    result = lint_blade(root, _catalog("blade-l4", [("t_aliased", "structured")]))
    assert result.tools["t_aliased"]["audit_surface"]["result"] == "match"


# ---------------------------------------------------------------------------
#  L5 — indirect via wrapper function
# ---------------------------------------------------------------------------


def test_l5_indirect_via_wrapper(tmp_path: Path) -> None:
    """Tool calls _finalize() whose body calls append_meta → match."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

def _finalize(body, **meta_kwargs):
    return append_meta(body, meta_envelope(**meta_kwargs))

@mcp.tool()
async def t_wrapped() -> str:
    return _finalize("body", matched_total=1, returned=1, latency_ms=1)
"""
    root = _write_blade(tmp_path, package="bladeL5", server_body=server)
    result = lint_blade(root, _catalog("blade-l5", [("t_wrapped", "structured")]))
    verdict = result.tools["t_wrapped"]["audit_surface"]
    assert verdict["result"] == "match", verdict["detail"]


# ---------------------------------------------------------------------------
#  L6 — catalog says minimal but tool DOES emit → under-declared
# ---------------------------------------------------------------------------


def test_l6_minimal_declared_but_emits(tmp_path: Path) -> None:
    """Catalog declares minimal but tool calls append_meta → under-declared."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_undersold() -> str:
    return append_meta("b", meta_envelope(matched_total=0, returned=0, latency_ms=0))
"""
    root = _write_blade(tmp_path, package="bladeL6", server_body=server)
    result = lint_blade(root, _catalog("blade-l6", [("t_undersold", "minimal")]))
    verdict = result.tools["t_undersold"]["audit_surface"]
    assert verdict["result"] == "under-declared"


# ---------------------------------------------------------------------------
#  L7 — catalog says minimal and tool does not emit → match
# ---------------------------------------------------------------------------


def test_l7_minimal_declared_no_emit(tmp_path: Path) -> None:
    """Catalog declares minimal; tool does not call append_meta → match."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_honest_minimal() -> str:
    return "plain"
"""
    root = _write_blade(tmp_path, package="bladeL7", server_body=server)
    result = lint_blade(root, _catalog("blade-l7", [("t_honest_minimal", "minimal")]))
    verdict = result.tools["t_honest_minimal"]["audit_surface"]
    assert verdict["result"] == "match"


# ---------------------------------------------------------------------------
#  L8 — audit_surface=none → always match
# ---------------------------------------------------------------------------


def test_l8_none_always_match(tmp_path: Path) -> None:
    """audit_surface=none is byte-blob payload; emission status N/A → always match."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_bytes() -> bytes:
    return b"\\x00\\x01"
"""
    root = _write_blade(tmp_path, package="bladeL8", server_body=server)
    result = lint_blade(root, _catalog("blade-l8", [("t_bytes", "none")]))
    verdict = result.tools["t_bytes"]["audit_surface"]
    assert verdict["result"] == "match"


# ---------------------------------------------------------------------------
#  L9 — tool not found in source tree
# ---------------------------------------------------------------------------


def test_l9_tool_not_found(tmp_path: Path) -> None:
    """Catalog references a tool that has no matching @mcp.tool function."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def real_tool() -> str:
    return ""
"""
    root = _write_blade(tmp_path, package="bladeL9", server_body=server)
    result = lint_blade(root, _catalog("blade-l9", [("phantom_tool", "structured")]))
    verdict = result.tools["phantom_tool"]["audit_surface"]
    assert verdict["result"] == "indeterminate"
    assert verdict["actual"] == "indeterminate"
    assert "no function definition" in verdict["detail"]


# ---------------------------------------------------------------------------
#  L10 — summary aggregation across multiple tools
# ---------------------------------------------------------------------------


def test_l10_summary_aggregation(tmp_path: Path) -> None:
    """5-tool mixed blade exercises every counter slot."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_match_struct() -> str:
    return append_meta("b", meta_envelope(matched_total=0, returned=0, latency_ms=0))

@mcp.tool()
async def t_over() -> str:
    return "no envelope"

@mcp.tool()
async def t_under() -> str:
    return append_meta("b", meta_envelope(matched_total=0, returned=0, latency_ms=0))

@mcp.tool()
async def t_match_min() -> str:
    return "plain"
"""
    root = _write_blade(tmp_path, package="bladeL10", server_body=server)
    catalog = _catalog(
        "blade-l10",
        [
            ("t_match_struct", "structured"),
            ("t_over", "structured"),
            ("t_under", "minimal"),
            ("t_match_min", "minimal"),
            ("phantom", "structured"),  # indeterminate path
        ],
    )
    result = lint_blade(root, catalog)
    summary = result.summary
    assert summary["tools_checked"] == 5
    assert summary["match_count"] == 2
    assert summary["over_declared_count"] == 1
    assert summary["under_declared_count"] == 1
    assert summary["indeterminate_count"] == 1


# ---------------------------------------------------------------------------
#  L11 — JSON contract shape
# ---------------------------------------------------------------------------


def test_l11_json_shape(tmp_path: Path) -> None:
    """to_dict() round-trips through JSON and carries the documented schema."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_only() -> str:
    return "plain"
"""
    root = _write_blade(tmp_path, package="bladeL11", server_body=server)
    result = lint_blade(root, _catalog("blade-l11", [("t_only", "minimal")]))
    payload = result.to_dict()
    # Round-trip through JSON to prove serialisability.
    rendered = json.dumps(payload, sort_keys=True)
    reloaded = json.loads(rendered)
    assert set(reloaded.keys()) == {
        "blade",
        "tested_at",
        "harness_version",
        "lint_rule",
        "tools",
        "summary",
    }
    assert reloaded["lint_rule"] == LINT_RULE_ID
    assert reloaded["blade"] == "blade-l11"
    inner = reloaded["tools"]["t_only"]
    assert set(inner.keys()) == {"audit_surface"}
    assert set(inner["audit_surface"].keys()) == {
        "declared",
        "actual",
        "result",
        "detail",
    }
    assert set(reloaded["summary"].keys()) == {
        "tools_checked",
        "match_count",
        "over_declared_count",
        "under_declared_count",
        "indeterminate_count",
    }


# ---------------------------------------------------------------------------
#  Bare-decorator shape (``@mcp.tool`` without parens) — important coverage
# ---------------------------------------------------------------------------


def test_bare_decorator_shape(tmp_path: Path) -> None:
    """``@mcp.tool`` (no parens) is the FastMCP shorthand — same registration shape."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, fn): return fn

mcp = _M()

@mcp.tool
async def t_bare() -> str:
    return append_meta("b", meta_envelope(matched_total=0, returned=0, latency_ms=0))
"""
    root = _write_blade(tmp_path, package="bladeBare", server_body=server)
    result = lint_blade(root, _catalog("blade-bare", [("t_bare", "structured")]))
    assert result.tools["t_bare"]["audit_surface"]["result"] == "match"


# ---------------------------------------------------------------------------
#  Explicit name= kwarg on decorator
# ---------------------------------------------------------------------------


def test_explicit_name_kwarg(tmp_path: Path) -> None:
    """``@mcp.tool(name="X")`` registers the function under the X tool name."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool(name="syncthing_thing")
async def python_fn_name() -> str:
    return append_meta("b", meta_envelope(matched_total=0, returned=0, latency_ms=0))
"""
    root = _write_blade(tmp_path, package="bladeName", server_body=server)
    result = lint_blade(
        root,
        _catalog("blade-name", [("syncthing_thing", "structured")]),
    )
    assert result.tools["syncthing_thing"]["audit_surface"]["result"] == "match"


# ---------------------------------------------------------------------------
#  Unrecognised audit_surface value → indeterminate (defensive path)
# ---------------------------------------------------------------------------


def test_unknown_declared_value(tmp_path: Path) -> None:
    """Catalog with junk audit_surface value falls through to indeterminate."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_junk() -> str:
    return ""
"""
    root = _write_blade(tmp_path, package="bladeJunk", server_body=server)
    result = lint_blade(root, _catalog("blade-junk", [("t_junk", "totally-bogus")]))
    verdict = result.tools["t_junk"]["audit_surface"]
    assert verdict["result"] == "indeterminate"
    assert "unrecognised audit_surface" in verdict["detail"]


# ---------------------------------------------------------------------------
#  Unparseable source — must NOT crash; module just gets skipped.
# ---------------------------------------------------------------------------


def test_unparseable_source_skipped(tmp_path: Path) -> None:
    """A SyntaxError in one file should not crash the resolver."""
    server = """
from stallari_mcp_helpers import append_meta, meta_envelope

class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_ok() -> str:
    return append_meta("b", meta_envelope(matched_total=0, returned=0, latency_ms=0))
"""
    root = _write_blade(
        tmp_path,
        package="bladeBroken",
        server_body=server,
        extra_modules={"broken": "this is not valid python ::::\n"},
    )
    result = lint_blade(root, _catalog("blade-broken", [("t_ok", "structured")]))
    assert result.tools["t_ok"]["audit_surface"]["result"] == "match"


# ---------------------------------------------------------------------------
#  CLI smoke — write sidecar to disk + strict-mode exit code
# ---------------------------------------------------------------------------


def test_cli_writes_sidecar_and_exits_strict(tmp_path: Path) -> None:
    """End-to-end CLI test: build a blade, write a catalog, run --strict, check rc."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t_silent() -> str:
    return "no envelope"
"""
    root = _write_blade(tmp_path, package="bladeCli", server_body=server)
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(_catalog("blade-cli", [("t_silent", "structured")])),
        encoding="utf-8",
    )
    output_path = tmp_path / "sidecar.json"
    rc = _cli(
        [
            str(root),
            "--catalog",
            str(catalog_path),
            "--output",
            str(output_path),
            "--strict",
        ]
    )
    assert rc == 1  # over-declared trips --strict
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["lint_rule"] == LINT_RULE_ID
    assert payload["summary"]["over_declared_count"] == 1


def test_cli_no_strict_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Without --strict, lint always returns 0 even with verdict failures."""
    server = """
class _M:
    def tool(self, *a, **kw):
        def deco(fn): return fn
        return deco

mcp = _M()

@mcp.tool()
async def t() -> str:
    return ""
"""
    root = _write_blade(tmp_path, package="bladeCliOk", server_body=server)
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(_catalog("blade-cli-ok", [("t", "structured")])),
        encoding="utf-8",
    )
    rc = _cli([str(root), "--catalog", str(catalog_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert LINT_RULE_ID in captured.out


def test_cli_missing_catalog_returns_2(tmp_path: Path) -> None:
    """CLI returns exit code 2 when the catalog path can't be opened."""
    rc = _cli([str(tmp_path), "--catalog", str(tmp_path / "nope.json")])
    assert rc == 2


# ---------------------------------------------------------------------------
#  Module attribute presence
# ---------------------------------------------------------------------------


def test_public_constants_exported() -> None:
    """The canonical constants are reachable from the lint module surface."""
    assert CANONICAL_EMIT_NAME == "append_meta"
    assert LINT_RULE_ID == "S-AUD-001"


def test_lint_result_frozen() -> None:
    """LintResult is a frozen dataclass — verdicts shouldn't be mutated in-place."""
    result = LintResult(
        blade="x",
        tested_at="t",
        harness_version="0",
        tools={},
        summary={},
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        result.blade = "y"  # type: ignore[misc]
