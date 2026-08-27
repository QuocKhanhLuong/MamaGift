"""Security tests guarding against direct Supabase PostgREST data exposure.

Ensures that private database tables cannot be accessed directly via Supabase's
PostgREST Data API without going through the FastAPI application boundary, and verifies
statically that the web frontend does not introduce direct browser-to-database or
unmediated fetch/Supabase transports.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import httpx
import pytest

from app.models import Base

# Repository root (two levels up from tests/security)
REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
WEB_SRC: Final[Path] = REPO_ROOT / "apps" / "web" / "src"
WEB_PACKAGE_JSON: Final[Path] = REPO_ROOT / "apps" / "web" / "package.json"

# All private database tables containing application or user data.
# Must match Base.metadata.tables (minus any genuinely public tables).
PRIVATE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "documents",
        "jobs",
        "parse_runs",
        "feedback_events",
        "document_chunks",
    }
)

# Genuinely public tables (if any exist in the future).
PUBLIC_TABLES: Final[frozenset[str]] = frozenset()

# Tables that exist in the migrated database but are not SQLAlchemy models, so
# `Base.metadata` cannot enumerate them. They still reach the Data API if a schema is
# exposed, so the live probe must cover them explicitly. `test_private_tables_are_enumerated`
# deliberately does NOT include these -- it guards the model-derived set.
NON_MODEL_TABLES: Final[frozenset[str]] = frozenset({"app_metadata", "alembic_version"})

# Everything the anonymous probe must be refused on.
PROBED_TABLES: Final[frozenset[str]] = PRIVATE_TABLES | NON_MODEL_TABLES

# Forbidden client tokens in web bundle and package.json
FORBIDDEN_SUPABASE_TOKENS: Final[tuple[str, ...]] = (
    "@supabase/supabase-js",
    "createClient(",
    "supabase.co",
    "SUPABASE_ANON_KEY",
    "VITE_SUPABASE",
)

# Forbidden database connection strings in web source files
FORBIDDEN_DB_TOKENS: Final[tuple[str, ...]] = (
    "postgresql://",
    "postgres://",
    "psycopg",
)

# The single transport file in apps/web allowed to make bare fetch calls
ALLOWED_FETCH_FILES: Final[frozenset[str]] = frozenset(
    {
        "apps/web/src/api/client.ts",
    }
)

IGNORED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        "dist",
        ".git",
        "__pycache__",
        ".turbo",
        ".next",
        "build",
    }
)


def _iter_web_src_files(root: Path) -> list[Path]:
    """Recursively collect all files under root, skipping node_modules and dist."""
    files: list[Path] = []
    if not root.exists():
        return files
    for entry in root.rglob("*"):
        if entry.is_file():
            if not any(part in IGNORED_DIR_NAMES for part in entry.parts):
                files.append(entry)
    return sorted(files)


# ---------------------------------------------------------------------------
# Layer 1 — STRUCTURAL (always runs, no credentials needed)
# ---------------------------------------------------------------------------


def test_web_bundle_has_no_supabase_client() -> None:
    """Assert no Supabase client libraries, URLs, or anon keys are in web src or package.json."""
    targets = _iter_web_src_files(WEB_SRC)
    if WEB_PACKAGE_JSON.exists():
        targets.append(WEB_PACKAGE_JSON)

    assert targets, (
        f"Expected web files to check, but found none at {WEB_SRC} and {WEB_PACKAGE_JSON}"
    )

    violations: list[str] = []
    for file_path in targets:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for token in FORBIDDEN_SUPABASE_TOKENS:
            if token in content:
                rel_path = file_path.relative_to(REPO_ROOT)
                violations.append(f"{rel_path}: contains forbidden token '{token}'")

    assert not violations, (
        "Direct Supabase client or credentials detected in web application code:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_web_has_no_database_url() -> None:
    """Assert no file under apps/web/src/** contains database URLs or connection drivers."""
    targets = _iter_web_src_files(WEB_SRC)
    assert targets, f"Expected web source files to check at {WEB_SRC}"

    violations: list[str] = []
    for file_path in targets:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for token in FORBIDDEN_DB_TOKENS:
            if token in content:
                rel_path = file_path.relative_to(REPO_ROOT)
                violations.append(f"{rel_path}: contains forbidden DB token '{token}'")

    assert not violations, (
        "Direct database connection strings or drivers detected in web source code:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_web_network_calls_go_through_the_api_client() -> None:
    """Assert every fetch/axios call in apps/web/src/** lives only in apps/web/src/api/client.ts."""
    targets = _iter_web_src_files(WEB_SRC)
    assert targets, f"Expected web source files to check at {WEB_SRC}"

    actual_fetch_files: set[str] = set()
    axios_violations: list[str] = []

    for file_path in targets:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        rel_path = file_path.relative_to(REPO_ROOT).as_posix()

        # Check for bare fetch( invocation
        if "fetch(" in content:
            actual_fetch_files.add(rel_path)

        # Check for axios usage
        if "axios" in content:
            axios_violations.append(f"{rel_path}: contains 'axios'")

    assert not axios_violations, (
        "Axios network library usage detected in web source code (must use api/client.ts):\n"
        + "\n".join(f"  - {v}" for v in axios_violations)
    )

    assert actual_fetch_files == ALLOWED_FETCH_FILES, (
        "Network fetch calls detected outside allowed transport client(s).\n"
        f"  Allowed: {sorted(ALLOWED_FETCH_FILES)}\n"
        f"  Actual:  {sorted(actual_fetch_files)}\n"
        f"  Unexpected: {sorted(actual_fetch_files - ALLOWED_FETCH_FILES)}\n"
        f"  Missing:    {sorted(ALLOWED_FETCH_FILES - actual_fetch_files)}"
    )


def test_private_tables_are_enumerated() -> None:
    """Assert the constant list of private table names equals declared SQLAlchemy models."""
    model_tables = set(Base.metadata.tables.keys()) - PUBLIC_TABLES
    assert PRIVATE_TABLES == model_tables, (
        "Mismatch between classified PRIVATE_TABLES constant and declared SQLAlchemy models!\n"
        f"  Unclassified model tables: {sorted(model_tables - PRIVATE_TABLES)}\n"
        f"  Extraneous private tables: {sorted(PRIVATE_TABLES - model_tables)}\n"
        "If a new table was added, classify it in PRIVATE_TABLES (or PUBLIC_TABLES if public)."
    )


# ---------------------------------------------------------------------------
# Layer 2 — LIVE PROBE (skipped unless credentials exist)
# ---------------------------------------------------------------------------


def test_anonymous_data_api_cannot_read_private_tables() -> None:
    """Probe live Supabase PostgREST Data API with anon key to assert private tables are blocked."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")

    if not supabase_url or not supabase_anon_key:
        pytest.skip(
            "SUPABASE_URL/SUPABASE_ANON_KEY are not set; live Supabase exposure probe NOT_RUN "
            "(BLOCKED_BY_CREDENTIALS)"
        )

    base_url = supabase_url.rstrip("/")
    headers = {
        "apikey": supabase_anon_key,
        "Authorization": f"Bearer {supabase_anon_key}",
    }

    unsafe_exposures: list[str] = []

    with httpx.Client(timeout=5.0) as client:
        for table in sorted(PROBED_TABLES):
            target_url = f"{base_url}/rest/v1/{table}?select=*&limit=1"
            try:
                response = client.get(target_url, headers=headers)
            except httpx.RequestError as exc:
                pytest.fail(
                    f"Network error while probing table '{table}' on Supabase Data API "
                    f"at {target_url}: {exc}"
                )

            # SAFE results: HTTP 401, 403, 404, or standard PostgREST error payload
            if response.status_code in (401, 403, 404):
                continue

            # Check if response is HTTP 200 with a JSON array
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception as exc:
                    unsafe_exposures.append(
                        f"Table '{table}' returned HTTP 200 with non-JSON body: "
                        f"{response.text[:200]} ({exc})"
                    )
                    continue

                if isinstance(data, list):
                    # An array (whether with records or empty []) proves table read access
                    if len(data) > 0:
                        unsafe_exposures.append(
                            f"Table '{table}' EXPOSED: HTTP 200 returned {len(data)} record(s). "
                            f"Sample: {str(data[0])[:150]}"
                        )
                    else:
                        unsafe_exposures.append(
                            f"Table '{table}' EXPOSED: HTTP 200 returned empty array []. "
                            "An empty array proves the table is readable anonymously and merely "
                            "empty, which constitutes unauthorized data exposure."
                        )
                else:
                    unsafe_exposures.append(
                        f"Table '{table}' returned unexpected HTTP 200 JSON object: "
                        f"{str(data)[:200]}"
                    )
            elif response.status_code >= 400:
                # Any 4xx/5xx error indicates access was refused or route was unmapped (SAFE)
                continue
            else:
                unsafe_exposures.append(
                    f"Table '{table}' returned unexpected HTTP status {response.status_code}: "
                    f"{response.text[:200]}"
                )

    assert not unsafe_exposures, (
        "RELEASE BLOCKING: Anonymous Supabase Data API read probe detected exposed "
        "private tables!\n" + "\n".join(f"  - {exp}" for exp in unsafe_exposures)
    )
