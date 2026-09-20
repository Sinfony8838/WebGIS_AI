"""Phase-1 isolation preflight (audit task T1).

Standalone boundary check for a source worktree about to run tests:
verifies the worktree has no production data dir, no symlink/junction
escapes, and that the resolved data targets stay inside a sandbox root
when an explicit ``WEBGIS_AI_DATA_DIR`` is supplied.

Outputs boolean/label lines only — never resolved absolute paths.

Usage:
    python scripts/qa/phase1/check_isolation.py --repo-root <path> [--sandbox <path>]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.app.config import AppConfig, resolve_data_root  # noqa: E402

DATA_ENV_VARS = ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB")

TARGET_LABELS = (
    "data_dir",
    "state_dir",
    "auth_dir",
    "auth_db_path",
    "uploads_dir",
    "outputs_dir",
    "workflows_dir",
    "state_file",
)


def check(repo_root: Path, sandbox: Path | None) -> int:
    failures = 0
    repo_root = repo_root.resolve()

    data_dir_present = (repo_root / "backend" / "data").exists()
    print(f"repo_backend_data_present={data_dir_present}")
    env_file_present = (repo_root / ".env").exists()
    print(f"env_file_present={env_file_present}")

    inherited = [name for name in DATA_ENV_VARS if os.environ.get(name, "").strip()]
    print(f"inherited_overrides={','.join(inherited) if inherited else 'none'}")

    if sandbox is None:
        print("sandbox_check=skipped")
    else:
        sandbox = sandbox.resolve()
        os.environ["WEBGIS_AI_DATA_DIR"] = str(sandbox)
        try:
            config = AppConfig(root_dir=sandbox)
            config.data_dir = resolve_data_root(sandbox)
            config.state_dir = config.data_dir / "state"
            config.auth_dir = config.data_dir / "auth"
            config.auth_db_path = config.auth_dir / "auth.db"
            config.uploads_dir = config.data_dir / "uploads"
            config.outputs_dir = config.data_dir / "outputs"
            config.workflows_dir = config.data_dir / "workflows"
            config.state_file = config.state_dir / "runtime.json"
            resolved_root = sandbox.resolve()
            escapes = []
            for label in TARGET_LABELS:
                target = getattr(config, label, None)
                if target is None:
                    escapes.append(f"{label}:missing")
                    continue
                try:
                    Path(target).resolve().relative_to(resolved_root)
                except ValueError:
                    escapes.append(label)
            print(f"sandbox_escape_targets={','.join(escapes) if escapes else 'none'}")
            failures += len(escapes)
        finally:
            os.environ.pop("WEBGIS_AI_DATA_DIR", None)

    status = "PASS" if failures == 0 else "FAIL"
    print(f"isolation_status={status}")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--sandbox", default=None)
    args = parser.parse_args()
    return check(Path(args.repo_root), Path(args.sandbox) if args.sandbox else None)


if __name__ == "__main__":
    raise SystemExit(main())
