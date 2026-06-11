"""Smoke test — verifies the package imports cleanly.

Comprehensive tests for `domain_hint` and `audit_envelope` ship in
`test_domain_hint.py` + `test_audit_envelope.py` (Spec A v2 subagent).
This file exists to keep CI green on the scaffold commit before those
land, and as a permanent import-smoke guard going forward.
"""

from __future__ import annotations


def test_package_imports() -> None:
    import stallari_mcp_helpers

    assert stallari_mcp_helpers.__version__ == "0.4.0"
