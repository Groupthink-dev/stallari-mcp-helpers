"""Static AST-based audit-surface honesty linter (S-AUD-001).

DD-338 Phase B Python implementation of the cross-language lint rule:
"every blade-mcp tool whose catalog declares ``granularity.audit_surface ==
'structured'`` must have its response builder invoke the canonical
``append_meta`` helper from ``stallari_mcp_helpers``."

This module is the static analog of the live conformance probe at
``stallari_capability_conformance.probe.LiveMCPToolProbe``. It walks the
blade-mcp's Python source tree, identifies MCP tool functions by their
FastMCP decorator shape (``@mcp.tool()``, ``@mcp.tool(name=...)``,
``@server.tool``, ``@app.tool`` — any ``.tool`` attribute on any module
name), and verifies whether each tool function transitively emits the
``_meta`` envelope.

Public API
----------

- :func:`lint_blade` — main entrypoint; takes a Python source root + parsed
  catalog dict and returns a :class:`LintResult`.
- :class:`LintResult` — verdict aggregate with ``to_dict()`` mirroring the
  live probe's sidecar JSON shape.
- :func:`_cli` — console script entrypoint registered as
  ``stallari-mcp-lint`` in ``pyproject.toml``.

The lint runs without spawning subprocesses or requiring credentials so it
is cheap to run in CI on every PR. False positives (over-declared) and
false negatives (under-declared) are the two failure modes; the lint
favours ``indeterminate`` over guessing when patterns fall outside the
recognised set.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The canonical emit name we trace through the resolution graph. A tool
# function "emits" if its body calls any name that resolves transitively
# (up to ``_MAX_RESOLUTION_DEPTH`` wrapper hops) to this identifier from
# the ``stallari_mcp_helpers`` package.
CANONICAL_EMIT_NAME = "append_meta"
CANONICAL_LIB_PACKAGE = "stallari_mcp_helpers"

# Maximum number of wrapper-function hops the resolver will follow when
# determining whether an in-blade name is an alias of ``append_meta``.
# Three hops handles the common patterns:
#   1. direct import + call
#   2. re-export from a sibling module (e.g. ``formatters.append_meta``)
#   3. wrapper function whose body calls ``append_meta``
# Deeper indirection is reported as ``indeterminate`` rather than guessed.
_MAX_RESOLUTION_DEPTH = 3

# The lint rule identifier surfaced in the sidecar JSON.
LINT_RULE_ID = "S-AUD-001"


# ---------------------------------------------------------------------------
#  Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LintResult:
    """Aggregate verdict produced by :func:`lint_blade`.

    Per-tool verdicts live in :attr:`tools` keyed by tool name; each value
    is a dict with the inner ``audit_surface`` block matching the live
    probe's sidecar JSON shape so a single rendering surface (the
    Astrolabe Releases pane, the conformance CLI's stdout) can consume
    both static and runtime verdicts uniformly.
    """

    blade: str
    tested_at: str
    harness_version: str
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render the verdict envelope as a JSON-serialisable dict."""
        return {
            "blade": self.blade,
            "tested_at": self.tested_at,
            "harness_version": self.harness_version,
            "lint_rule": LINT_RULE_ID,
            "tools": dict(self.tools),
            "summary": dict(self.summary),
        }


# ---------------------------------------------------------------------------
#  Source-tree resolver
# ---------------------------------------------------------------------------


@dataclass
class _ModuleInfo:
    """Parsed view of one Python source file in the blade's tree."""

    path: Path
    tree: ast.AST
    # Names bound in this module that resolve to canonical append_meta.
    # Populated lazily by :class:`_Resolver` once the whole tree is parsed.
    canonical_names: set[str] = field(default_factory=set)
    # Tool functions defined in this module, indexed by tool name (as
    # declared by the catalog — either ``name=`` kwarg on the decorator
    # or the bare function name).
    tools: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    # Imports as ``{local_name: (origin_module, original_name)}``. ``origin_module``
    # is the fully qualified module path as written (we don't resolve relative
    # imports here — those are tracked separately by the relative-import map).
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Module-level assignments ``Name = OtherName`` for alias detection.
    aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class _Resolver:
    """Whole-blade resolution graph.

    Built once per :func:`lint_blade` call by parsing every ``.py`` file
    under the blade source root, then queried per tool function to decide
    emission status.
    """

    root: Path
    modules: dict[str, _ModuleInfo] = field(default_factory=dict)

    @classmethod
    def build(cls, root: Path) -> _Resolver:
        """Walk ``root`` and parse every ``.py`` file into a module info map.

        Modules are keyed by their dotted module path relative to ``root``
        (e.g. ``syncthing_mcp.tools.devices``). Files that fail to parse
        are skipped with a warning; the lint reports indeterminate rather
        than crashing — a syntax-broken blade has bigger problems than
        audit-surface honesty.
        """
        resolver = cls(root=root)
        py_files = sorted(root.rglob("*.py"))
        for py_path in py_files:
            # Skip __pycache__ and dot-prefixed directories.
            if any(part.startswith(".") or part == "__pycache__" for part in py_path.parts):
                continue
            module_name = _path_to_module(py_path, root)
            try:
                source = py_path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            info = _ModuleInfo(path=py_path, tree=tree)
            _collect_module_facts(info, tree)
            resolver.modules[module_name] = info
        # Two-pass canonical name propagation: until fixed point, follow
        # cross-module re-exports so a name imported from a sibling
        # eventually traces back to ``stallari_mcp_helpers.append_meta``.
        resolver._propagate_canonical_names()
        return resolver

    def _propagate_canonical_names(self) -> None:
        """Iterate the resolution graph until canonical-name sets stabilise.

        Each iteration adds names that re-export, alias, or wrap an
        already-canonical name. Bounded by ``_MAX_RESOLUTION_DEPTH``
        passes — anything deeper is treated as indeterminate.
        """
        for _ in range(_MAX_RESOLUTION_DEPTH):
            changed = False
            for module in self.modules.values():
                # Imports: ``from stallari_mcp_helpers import append_meta as X``
                # OR ``from .formatters import append_meta`` where the source
                # module already has it canonical.
                for local_name, (origin_mod, original_name) in module.imports.items():
                    if local_name in module.canonical_names:
                        continue
                    if _is_canonical_import(origin_mod, original_name):
                        module.canonical_names.add(local_name)
                        changed = True
                        continue
                    # Cross-module follow — try both fully qualified and
                    # relative-resolved forms.
                    candidate_module = self._resolve_module_ref(origin_mod, module)
                    if candidate_module is None:
                        continue
                    if original_name in candidate_module.canonical_names:
                        module.canonical_names.add(local_name)
                        changed = True
                # Aliases inside the module body.
                for alias_name, source_name in module.aliases.items():
                    if alias_name in module.canonical_names:
                        continue
                    if source_name in module.canonical_names:
                        module.canonical_names.add(alias_name)
                        changed = True
                # Wrapper functions: any module-level def whose body
                # contains a call to an already-canonical name becomes
                # canonical itself.
                for node in ast.iter_child_nodes(module.tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name in module.canonical_names:
                            continue
                        if _function_calls_canonical(node, module.canonical_names):
                            module.canonical_names.add(node.name)
                            changed = True
            if not changed:
                break

    def _resolve_module_ref(
        self,
        origin_mod: str,
        from_module: _ModuleInfo,
    ) -> _ModuleInfo | None:
        """Resolve a module reference to its parsed :class:`_ModuleInfo`.

        Handles fully-qualified absolute references (``syncthing_mcp.formatters``)
        AND relative references that were captured as ``.formatters`` —
        relative-import resolution is best-effort: we search every parsed
        module whose dotted path ends with the relative suffix.
        """
        # Absolute match.
        if origin_mod in self.modules:
            return self.modules[origin_mod]
        # Relative (starts with ``.``). Try suffix-match against parsed
        # modules. This isn't fully correct for relative-import semantics
        # but covers the common in-tree re-export pattern.
        if origin_mod.startswith("."):
            stripped = origin_mod.lstrip(".")
            if not stripped:
                return None
            # Prefer the candidate whose path is closest to the from-module.
            candidates = [
                mod_name
                for mod_name in self.modules
                if mod_name == stripped or mod_name.endswith("." + stripped)
            ]
            # Pick the shortest (most parent-ish) match if multiple — covers
            # the ``from .formatters import X`` case in nested tools/ dirs.
            if candidates:
                candidates.sort(key=lambda m: m.count("."))
                return self.modules[candidates[0]]
        # Try a last-resort match for absolute-but-not-found refs — the
        # blade may not be installed in the resolver's tree (e.g. just the
        # ``messages_blade_mcp`` package without its parent, OR the package
        # is rooted at ``syncthing_mcp/`` and an in-tree import does
        # ``from syncthing_mcp.formatters import ...``; the parsed module
        # is keyed as ``formatters`` not ``syncthing_mcp.formatters``).
        # We accept either direction:
        #   1. parsed module path ends with ``"." + origin_mod`` —
        #      origin_mod is the shorter/relative form.
        #   2. ``origin_mod`` ends with ``"." + parsed_module_path`` —
        #      origin_mod is the full qualified form and we parsed the
        #      package as if it were rooted (e.g. parsed ``formatters``
        #      matches ``syncthing_mcp.formatters``).
        suffix_matches = [
            m
            for m in self.modules
            if m.endswith("." + origin_mod) or origin_mod.endswith("." + m) or origin_mod == m
        ]
        if suffix_matches:
            suffix_matches.sort(key=lambda m: m.count("."))
            return self.modules[suffix_matches[0]]
        return None


def _is_canonical_import(origin_mod: str, original_name: str) -> bool:
    """``True`` if the import refers directly to ``stallari_mcp_helpers.append_meta``."""
    if original_name != CANONICAL_EMIT_NAME:
        return False
    if origin_mod == CANONICAL_LIB_PACKAGE:
        return True
    return origin_mod.startswith(CANONICAL_LIB_PACKAGE + ".")


def _function_calls_canonical(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    canonical_names: set[str],
) -> bool:
    """Walk ``fn``'s body for a call whose func name is in ``canonical_names``."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            target = _call_target_name(node)
            if target is not None and target in canonical_names:
                return True
    return False


def _call_target_name(call: ast.Call) -> str | None:
    """Extract the simple name being called (``foo`` from ``foo(...)`` or
    ``self.foo(...)`` or ``mod.foo(...)``). Returns ``None`` for unrecognised
    shapes."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _path_to_module(path: Path, root: Path) -> str:
    """Convert a filesystem path to a dotted module name relative to ``root``.

    The blade root may itself be a package directory (e.g.
    ``src/syncthing_mcp/``) or a parent directory containing the package.
    We normalise by stripping the ``.py`` suffix and joining the relative
    path parts with ``.``.
    """
    relative = path.relative_to(root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # drop .py
    return ".".join(parts)


# ---------------------------------------------------------------------------
#  Module-fact collection
# ---------------------------------------------------------------------------


def _collect_module_facts(info: _ModuleInfo, tree: ast.AST) -> None:
    """Populate ``info.imports``, ``info.aliases``, and ``info.tools``."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            module_ref = ("." * (node.level or 0)) + (node.module or "")
            for alias in node.names:
                local_name = alias.asname or alias.name
                info.imports[local_name] = (module_ref, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                info.imports[local_name] = (alias.name, alias.name)
        elif isinstance(node, ast.Assign):
            # ``X = Y`` simple aliases.
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Name)
            ):
                info.aliases[node.targets[0].id] = node.value.id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tool_name = _tool_name_from_decorators(node)
            if tool_name is not None:
                info.tools[tool_name] = node


def _tool_name_from_decorators(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """If ``fn`` has a FastMCP-style tool decorator, return the registered
    tool name; otherwise ``None``.

    Accepted decorator shapes (any module prefix — ``mcp``, ``server``,
    ``app``, ``self.mcp``, etc.):

    - ``@<x>.tool``                   — no-paren, name = fn.__name__
    - ``@<x>.tool()``                 — paren no kwargs, name = fn.__name__
    - ``@<x>.tool(name="...")``       — explicit name kwarg
    - ``@<x>.tool(name="...", ...)``  — name plus other kwargs (annotations etc.)

    Imperative ``server.add_tool(fn, name="...")`` is NOT detected by this
    helper — it's handled (or marked indeterminate) at the catalog-matching
    layer below.
    """
    for decorator in fn.decorator_list:
        if isinstance(decorator, ast.Attribute) and decorator.attr == "tool":
            return fn.name
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                for kw in decorator.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        value = kw.value.value
                        if isinstance(value, str):
                            return value
                return fn.name
    return None


# ---------------------------------------------------------------------------
#  Per-tool verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ToolVerdict:
    """Internal carrier for a single tool's audit-surface verdict."""

    declared: str
    actual: str
    result: str
    detail: str

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {
            "audit_surface": {
                "declared": self.declared,
                "actual": self.actual,
                "result": self.result,
                "detail": self.detail,
            }
        }


def _verdict_for_tool(
    tool_name: str,
    declared: str,
    fn: ast.FunctionDef | ast.AsyncFunctionDef | None,
    module: _ModuleInfo | None,
) -> _ToolVerdict:
    """Build the per-tool verdict from declaration + emission evidence."""
    if declared == "none":
        return _ToolVerdict(
            declared="none",
            actual="indeterminate",
            result="match",
            detail=(
                "audit_surface=none — tool returns byte payloads where the "
                "_meta envelope is N/A; emission status is not inspected."
            ),
        )

    if fn is None or module is None:
        return _ToolVerdict(
            declared=declared,
            actual="indeterminate",
            result="indeterminate",
            detail=(
                f"no function definition matched tool name {tool_name!r} in "
                "the source tree (catalog name without a corresponding "
                "@mcp.tool-decorated function — may be registered "
                "imperatively via server.add_tool, which this lint does "
                "not statically resolve)"
            ),
        )

    emits = _function_calls_canonical(fn, module.canonical_names)
    actual = "structured" if emits else "minimal"

    if declared == "structured":
        if emits:
            return _ToolVerdict(
                declared="structured",
                actual="structured",
                result="match",
                detail=(
                    "tool body calls append_meta (directly or via a resolved wrapper / re-export)."
                ),
            )
        return _ToolVerdict(
            declared="structured",
            actual="minimal",
            result="over-declared",
            detail=(
                "catalog declares audit_surface=structured but tool body "
                "does not call append_meta within the resolved emission "
                f"graph (depth ≤{_MAX_RESOLUTION_DEPTH})."
            ),
        )

    if declared == "minimal":
        if emits:
            return _ToolVerdict(
                declared="minimal",
                actual="structured",
                result="under-declared",
                detail=(
                    "catalog declares audit_surface=minimal but tool body "
                    "calls append_meta — declare structured instead."
                ),
            )
        return _ToolVerdict(
            declared="minimal",
            actual="minimal",
            result="match",
            detail="catalog declares minimal and tool does not call append_meta.",
        )

    # Unknown declared value — fall through.
    return _ToolVerdict(
        declared=declared,
        actual=actual,
        result="indeterminate",
        detail=(
            f"unrecognised audit_surface value {declared!r} in catalog; "
            "expected one of structured / minimal / none."
        ),
    )


# ---------------------------------------------------------------------------
#  Public entry — lint_blade
# ---------------------------------------------------------------------------


def lint_blade(
    blade_source_root: Path,
    catalog_entry: dict[str, Any],
) -> LintResult:
    """Statically lint a Python blade for DD-338 audit-surface honesty.

    Parameters
    ----------
    blade_source_root:
        Path to the blade's Python source. May be the repository root
        (e.g. ``~/src/syncthing-blade-mcp``) or the inner package
        directory (e.g. ``~/src/syncthing-blade-mcp/src/syncthing_mcp``).
        The walker rglobs ``.py`` files either way.
    catalog_entry:
        Parsed catalog JSON dict — the structure produced by
        :func:`stallari_capability_conformance.conformance.load_catalog_entry`.
        Must include ``name`` (blade slug) and ``tools`` (list of
        per-tool granularity declarations).

    Returns
    -------
    LintResult
        Per-tool verdicts + aggregate summary. Use :meth:`LintResult.to_dict`
        to render as JSON for sidecar storage.
    """
    blade_source_root = Path(blade_source_root).resolve()
    resolver = _Resolver.build(blade_source_root)

    # Build the global tool-name index (which module hosts which tool).
    tool_locations: dict[str, tuple[_ModuleInfo, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for module in resolver.modules.values():
        for tool_name, fn in module.tools.items():
            tool_locations[tool_name] = (module, fn)

    tools_block: dict[str, dict[str, Any]] = {}
    counts = {
        "match_count": 0,
        "over_declared_count": 0,
        "under_declared_count": 0,
        "indeterminate_count": 0,
    }

    catalog_tools = catalog_entry.get("tools") or []
    for tool_entry in catalog_tools:
        tool_name = tool_entry.get("name")
        if not isinstance(tool_name, str):
            continue
        granularity = tool_entry.get("granularity") or {}
        declared = granularity.get("audit_surface", "minimal")

        location = tool_locations.get(tool_name)
        if location is None:
            verdict = _verdict_for_tool(tool_name, declared, None, None)
        else:
            module, fn = location
            verdict = _verdict_for_tool(tool_name, declared, fn, module)

        tools_block[tool_name] = verdict.as_dict()
        result_key = verdict.result + "_count" if verdict.result != "match" else "match_count"
        # Normalise hyphenated keys.
        if verdict.result == "over-declared":
            counts["over_declared_count"] += 1
        elif verdict.result == "under-declared":
            counts["under_declared_count"] += 1
        elif verdict.result == "match":
            counts["match_count"] += 1
        else:
            counts["indeterminate_count"] += 1
        del result_key  # nopep8 — unused alias kept for code-review clarity

    summary = {
        "tools_checked": len(tools_block),
        **counts,
    }

    from . import __version__

    return LintResult(
        blade=catalog_entry.get("name", str(blade_source_root.name)),
        tested_at=datetime.now(UTC).isoformat(timespec="seconds"),
        harness_version=__version__,
        tools=tools_block,
        summary=summary,
    )


# ---------------------------------------------------------------------------
#  Console-script entrypoint
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    """Argparse-driven CLI registered as ``stallari-mcp-lint``.

    Usage::

        stallari-mcp-lint <blade-source-root> --catalog <catalog-json>
                          [--output <sidecar.json>] [--strict]

    ``--strict`` exits non-zero on any over-declared / under-declared
    verdict (indeterminate verdicts do NOT trip strict mode — they are
    explicitly "lint can't tell" rather than "lint says wrong").
    """
    parser = argparse.ArgumentParser(
        prog="stallari-mcp-lint",
        description=(
            "Static audit-surface honesty linter for Stallari blade-mcps "
            "(S-AUD-001 / DD-338 Phase B)."
        ),
    )
    parser.add_argument(
        "source_root",
        type=Path,
        help="Path to the blade's Python source root (repo or package dir).",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Path to the blade's catalog JSON entry.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=("Optional sidecar JSON path. Without --output the verdict is printed to stdout."),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero on any over-declared / under-declared verdict. "
            "Indeterminate verdicts do not trip strict mode."
        ),
    )
    args = parser.parse_args(argv)

    catalog_path: Path = args.catalog
    try:
        with catalog_path.open("r", encoding="utf-8") as f:
            catalog_entry = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: failed to load catalog {catalog_path}: {exc}", file=sys.stderr)
        return 2

    result = lint_blade(args.source_root, catalog_entry)
    payload = json.dumps(result.to_dict(), indent=2, sort_keys=True)

    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    if args.strict:
        summary = result.summary
        if summary.get("over_declared_count", 0) or summary.get("under_declared_count", 0):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
