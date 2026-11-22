#!/usr/bin/env python3
"""Safe v2.4 update on top of installed RAG table v2.3.

--check: verify version checksums before modifying code.
--rollback: return to exact v2.3 code from per-file backups.
Never writes SQLite, PDFs, model settings, or .env.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / 'rag_table_v24_modules'
V22 = ROOT / 'rag_table_v22_install_manifest.json'
V23 = ROOT / 'rag_table_v23_install_manifest.json'
V24 = ROOT / 'rag_table_v24_install_manifest.json'
MODULES = (
    'app/services/rag_hierarchical_tables.py',  # new
    'app/services/rag_pdf_table_recovery.py',   # from v2.3
    'app/services/rag_table_extraction.py',     # from v2.2
    'app/services/grounding.py',                # existing common service
    'app/api/rag_table_routes.py',             # from v2.3
)
TEST = 'tests/test_rag_table_v24.py'
TARGETS = MODULES + (TEST,)
# v2.3 does not own grounding.py. To avoid overwriting local changes
# and breaking the other domain, require precisely the tested base revision.
GROUNDING_SHA = 'ac9ddece9d6131a581beb10d0ffbd5c816f77d50f2eb433865fd0dd3e9305063'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_entries(path: Path, version: str) -> dict[str, dict]:
    if not path.is_file():
        raise RuntimeError(f'Required {version} install manifest missing: {path.name}')
    obj = json.loads(path.read_text(encoding='utf-8'))
    if obj.get('version') != version or not isinstance(obj.get('files'), list):
        raise RuntimeError(f'Invalid {version} manifest: {path.name}')
    return {item['file']: item for item in obj['files']}


def preflight() -> list[tuple[str, bytes, bytes | None]]:
    if V24.exists():
        raise RuntimeError('v2.4 already installed; use --check or --rollback')
    if not (ROOT / 'dev.py').is_file():
        raise RuntimeError('Must run from the existing backend root containing dev.py')
    earlier = manifest_entries(V22, '2.2')
    recent = manifest_entries(V23, '2.3')
    mapping = {
        'app/services/rag_pdf_table_recovery.py': recent,
        'app/api/rag_table_routes.py': recent,
        'app/services/rag_table_extraction.py': earlier,
    }
    checked: list[tuple[str, bytes, bytes | None]] = []
    for rel in TARGETS:
        target = ROOT / rel
        raw = target.read_bytes() if target.is_file() else None
        proposed_file = PAYLOAD / rel if rel in MODULES else ROOT / 'rag_table_v24_tests' / rel
        if not proposed_file.is_file():
            raise RuntimeError(f'Missing update payload: {rel}')
        new = proposed_file.read_bytes()
        if rel.endswith('.py'):
            ast.parse(new.decode('utf-8'), filename=rel)
        if rel in mapping:
            if raw is None or digest(raw) != mapping[rel][rel]['installed_sha256']:
                raise RuntimeError(f'Local version changed for {rel}; not overwriting')
        elif rel == 'app/services/grounding.py':
            if raw is None or digest(raw) != GROUNDING_SHA:
                raise RuntimeError('Local app/services/grounding.py changed; merge manually rather than overwrite')
        elif raw is not None:
            raise RuntimeError(f'New file already exists: {rel}; not overwriting')
        checked.append((rel, new, raw))
    return checked


def apply() -> None:
    checked = preflight()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    changes: list[dict] = []
    try:
        for rel, new, old in checked:
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            backup = dest.with_name(dest.name + f'.before_rag_v24_{timestamp}.bak') if old is not None else None
            if backup and backup.exists():
                raise RuntimeError('Backup collision; nothing else is being overwritten')
            if backup:
                backup.write_bytes(old)
            tmp = dest.with_name(dest.name + '.rag_v24_tmp')
            changes.append({'file':rel, 'backup':str(backup.relative_to(ROOT)) if backup else None,
                            'old_sha256':digest(old) if old is not None else None,
                            'installed_sha256':digest(new)})
            tmp.write_bytes(new)
            tmp.replace(dest)
        V24.write_text(json.dumps({'version':'2.4','files':changes}, indent=2), encoding='utf-8')
    except Exception:
        for change in reversed(changes):
            dest = ROOT / change['file']
            backup = ROOT / change['backup'] if change['backup'] else None
            if backup is not None and backup.is_file():
                shutil.copy2(backup, dest)
            elif backup is None:
                dest.unlink(missing_ok=True)
            dest.with_name(dest.name + '.rag_v24_tmp').unlink(missing_ok=True)
        raise
    print('INSTALLED RAG Table v2.4: native 3-axis headers, scientific model context, leading decimals.')
    print('Existing SQLite, PDF files, results and .env left unchanged.')


def check() -> None:
    if V24.is_file():
        changes = manifest_entries(V24, '2.4')
        for rel, item in changes.items():
            p = ROOT / rel
            if not p.is_file() or digest(p.read_bytes()) != item['installed_sha256']:
                raise RuntimeError(f'Installed file changed: {rel}')
        print('OK: v2.4 installed, all checksums match')
    else:
        changes = preflight()
        print(f'OK: compatible v2.3 backend; {len(changes)} safe file updates ready')


def rollback() -> None:
    changes = manifest_entries(V24, '2.4')
    for rel, item in changes.items():
        p = ROOT / rel
        if not p.is_file() or digest(p.read_bytes()) != item['installed_sha256']:
            raise RuntimeError(f'Cannot rollback modified file: {rel}')
        if item['backup'] and not (ROOT / item['backup']).is_file():
            raise RuntimeError(f'Missing original backup for: {rel}')
    for rel, item in changes.items():
        p = ROOT / rel
        if item['backup']:
            shutil.copy2(ROOT / item['backup'], p)
        else:
            p.unlink(missing_ok=True)
    V24.unlink()
    print('ROLLED BACK to v2.3. PDF files and SQLite were not modified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true')
    group.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        if args.check:
            check()
        elif args.rollback:
            rollback()
        else:
            apply()
    except (KeyError, OSError, ValueError, RuntimeError, SyntaxError) as ex:
        print('ERROR:', ex, file=sys.stderr)
        raise SystemExit(1)
