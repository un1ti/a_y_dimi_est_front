#!/usr/bin/env python3
"""Install RAG table v2.3 diagnostics and geometry fixes over installed v2.2.

--check verifies compatibility, --rollback restores the exact v2.2 files.
Does not touch uploaded PDFs, SQLite, or .env.
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
PAYLOAD = ROOT / 'rag_table_v23_modules'
V22_MANIFEST = ROOT / 'rag_table_v22_install_manifest.json'
V23_MANIFEST = ROOT / 'rag_table_v23_install_manifest.json'
CODE_TARGETS = (
    'app/services/rag_pdf_table_recovery.py',
    'app/api/rag_table_routes.py',
)
TEST_TARGET = 'tests/test_rag_table_v23.py'
FILES = CODE_TARGETS + (TEST_TARGET,)


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def v22_entries() -> dict:
    if not (ROOT / 'dev.py').is_file():
        raise RuntimeError('Run from the existing backend directory containing dev.py')
    if not V22_MANIFEST.is_file():
        raise RuntimeError('RAG Table v2.2 manifest missing. Install v2.2 first; no files changed.')
    manifest = json.loads(V22_MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('version') != '2.2':
        raise RuntimeError('Expected installed RAG Table v2.2; no files changed')
    return {x['file']: x for x in manifest['files']}


def prepare() -> list[tuple[str, bytes, bytes | None]]:
    if V23_MANIFEST.exists():
        raise RuntimeError('v2.3 is already installed. Use --check or --rollback.')
    installed = v22_entries()
    prepared = []
    for rel in FILES:
        target = ROOT / rel
        if rel in CODE_TARGETS:
            if rel not in installed or not target.is_file():
                raise RuntimeError(f'Missing v2.2 module: {rel}')
            previous = target.read_bytes()
            if sha(previous) != installed[rel]['installed_sha256']:
                raise RuntimeError(f'File differs from installed v2.2: {rel}; no files changed.')
            proposed = (PAYLOAD / rel).read_bytes()
        else:
            previous = target.read_bytes() if target.is_file() else None
            proposed = (ROOT / 'rag_table_v23_test_files' / rel).read_bytes()
        if rel.endswith('.py'):
            ast.parse(proposed.decode('utf-8'), filename=rel)
        prepared.append((rel, proposed, previous))
    return prepared


def install() -> None:
    prepared = prepare()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    changes: list[dict] = []
    try:
        for rel, data, before in prepared:
            target = ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = (target.with_name(target.name + f'.before_rag_v23_{stamp}.bak') if before is not None else None)
            if backup is not None:
                if backup.exists():
                    raise RuntimeError(f'Backup collision: {backup}')
                backup.write_bytes(before)
            changes.append({
                'file': rel, 'backup': str(backup.relative_to(ROOT)) if backup else None,
                'previous_sha256': sha(before) if before is not None else None,
                'installed_sha256': sha(data),
            })
            tmp = target.with_name(target.name + '.rag-v23.tmp')
            tmp.write_bytes(data)
            tmp.replace(target)
        V23_MANIFEST.write_text(json.dumps({'version':'2.3', 'files':changes}, indent=2), encoding='utf-8')
    except Exception:
        for change in reversed(changes):
            target = ROOT / change['file']
            backup = ROOT / change['backup'] if change['backup'] else None
            if backup and backup.is_file():
                shutil.copy2(backup, target)
            elif backup is None:
                target.unlink(missing_ok=True)
        raise
    print('INSTALLED RAG Table v2.3: geometry fallback + diagnostics. Data files untouched.')


def check() -> None:
    if V23_MANIFEST.is_file():
        records = json.loads(V23_MANIFEST.read_text(encoding='utf-8'))['files']
        for item in records:
            target = ROOT / item['file']
            if not target.is_file() or sha(target.read_bytes()) != item['installed_sha256']:
                raise RuntimeError(f'Modified since v2.3 installation: {item["file"]}')
        print('OK: RAG Table v2.3 installed, files unchanged')
    else:
        prepared = prepare()
        print(f'OK: compatible RAG v2.2; {len(prepared)} files can be updated, DB untouched')


def rollback() -> None:
    if not V23_MANIFEST.is_file():
        raise RuntimeError('v2.3 manifest not found; nothing to rollback.')
    records = json.loads(V23_MANIFEST.read_text(encoding='utf-8'))['files']
    for change in records:
        target = ROOT / change['file']
        if not target.is_file() or sha(target.read_bytes()) != change['installed_sha256']:
            raise RuntimeError(f'Modified since install, cannot safely rollback: {change["file"]}')
        if change['backup'] and not (ROOT / change['backup']).is_file():
            raise RuntimeError(f'Backup missing: {change["backup"]}')
    for change in records:
        target = ROOT / change['file']
        if change['backup']:
            shutil.copy2(ROOT / change['backup'], target)
        else:
            target.unlink(missing_ok=True)
    V23_MANIFEST.unlink()
    print('ROLLED BACK to v2.2; no DB or PDF changes')


if __name__ == '__main__':
    cmd = argparse.ArgumentParser(description=__doc__)
    args = cmd.add_mutually_exclusive_group()
    args.add_argument('--check', action='store_true')
    args.add_argument('--rollback', action='store_true')
    opts = cmd.parse_args()
    try:
        if opts.check:
            check()
        elif opts.rollback:
            rollback()
        else:
            install()
    except (OSError, ValueError, KeyError, RuntimeError, SyntaxError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
