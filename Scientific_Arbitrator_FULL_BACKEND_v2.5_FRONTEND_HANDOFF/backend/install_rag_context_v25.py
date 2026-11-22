#!/usr/bin/env python3
"""Safe ADD ONLY v2.5 over exact installed v2.4; supports --check and --rollback."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / 'rag_context_v25_modules'
V24 = ROOT / 'rag_table_v24_install_manifest.json'
V25 = ROOT / 'rag_context_v25_install_manifest.json'
TARGETS = (
    'app/services/rag_publication_context.py',
    'app/api/scientific_routes.py',
    'app/api/quality_routes.py',
    'app/api/rag_profile_routes.py',
    'tests/test_rag_context_v25.py',
)
# Exact standard versions shipped with the installed v2.4 backend.
OLD_HASHES = {
    'app/api/scientific_routes.py': '7c4c69d23206a4df92276f76f8170342e0621f0d8f72c61f5fbd01a107bebd31',
    'app/api/quality_routes.py': '71f4ceb2d8ade21770bb5ab85dd7e64effceea377336e0e1ed8c8533be70a946',
    'app/api/rag_profile_routes.py': 'dd72868c2e261539e7e0673a8ee07b7374f4bd50b7ecdb7e1a6eca046c56d157',
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entries():
    if not V25.is_file():
        raise RuntimeError('v2.5 manifest not present')
    doc = json.loads(V25.read_text())
    if doc.get('version') != '2.5':
        raise RuntimeError('wrong v2.5 manifest')
    return doc['files']


def preflight():
    if not (ROOT / 'dev.py').is_file():
        raise RuntimeError('Run installer from existing backend root containing dev.py')
    if not V24.is_file() or json.loads(V24.read_text()).get('version') != '2.4':
        raise RuntimeError('Installed v2.4 manifest missing')
    if V25.is_file():
        raise RuntimeError('v2.5 already installed; use --check or --rollback')
    updates = []
    for rel in TARGETS:
        source = PAYLOAD / rel
        if not source.is_file():
            raise RuntimeError(f'Payload missing: {rel}')
        raw = source.read_bytes()
        ast.parse(raw.decode('utf-8'), filename=rel)
        dest = ROOT / rel
        old = dest.read_bytes() if dest.is_file() else None
        expected = OLD_HASHES.get(rel)
        if expected and (old is None or sha(old) != expected):
            raise RuntimeError(f'Local file modified: {rel}; refusing to overwrite')
        if expected is None and old is not None:
            raise RuntimeError(f'New file already exists: {rel}; refusing to overwrite')
        updates.append((rel, raw, old))
    return updates


def apply():
    updates = preflight()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    changes = []
    try:
        for rel, raw, old in updates:
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if old is not None:
                backup = dest.with_name(dest.name + '.before_rag_context_v25_' + stamp + '.bak')
                if backup.exists():
                    raise RuntimeError(f'Backup collision: {backup}')
                backup.write_bytes(old)
            changes.append({'file':rel,'backup':str(backup.relative_to(ROOT)) if backup else None,
                            'old_sha256':sha(old) if old is not None else None,
                            'installed_sha256':sha(raw)})
            tmp = dest.with_name(dest.name + '.v25_tmp')
            tmp.write_bytes(raw)
            tmp.replace(dest)
        V25.write_text(json.dumps({'version':'2.5','files':changes},indent=2),encoding='utf8')
    except Exception:
        for item in reversed(changes):
            dest = ROOT/item['file']
            if item['backup']:
                shutil.copy2(ROOT/item['backup'],dest)
            else:
                dest.unlink(missing_ok=True)
            dest.with_name(dest.name+'.v25_tmp').unlink(missing_ok=True)
        raise
    print('INSTALLED RAG Context v2.5; existing SQLite/PDFs/results/.env unchanged')


def check():
    if V25.is_file():
        for item in entries():
            dest = ROOT/item['file']
            if not dest.is_file() or sha(dest.read_bytes()) != item['installed_sha256']:
                raise RuntimeError('Modified v2.5 file: ' + item['file'])
        print('OK: v2.5 installed; all checksums match')
    else:
        print(f'OK: compatible v2.4 backend; {len(preflight())} updates ready')


def rollback():
    changes = entries()
    for item in changes:
        dest = ROOT/item['file']
        if not dest.is_file() or sha(dest.read_bytes()) != item['installed_sha256']:
            raise RuntimeError('Refusing rollback of modified file: '+item['file'])
        if item['backup'] and not (ROOT/item['backup']).is_file():
            raise RuntimeError('Missing backup for '+item['file'])
    for item in changes:
        dest = ROOT/item['file']
        if item['backup']:
            shutil.copy2(ROOT/item['backup'],dest)
        else:
            dest.unlink()
    V25.unlink()
    print('ROLLED BACK to v2.4; data untouched')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group()
    g.add_argument('--check',action='store_true')
    g.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    try:
        if args.check: check()
        elif args.rollback: rollback()
        else: apply()
    except (OSError, ValueError, RuntimeError, SyntaxError, KeyError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        raise SystemExit(1)
