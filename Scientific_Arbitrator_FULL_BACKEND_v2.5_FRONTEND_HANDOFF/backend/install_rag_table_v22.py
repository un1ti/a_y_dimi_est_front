#!/usr/bin/env python3
"""Install/rollback RAG table extraction v2.2 into an existing backend project.

No DB schema changes, no migration, no .env modifications and no PDF deletion.
Check all expected source anchors before modifying any file. Keep versioned backups.
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
MODULE_ROOT = ROOT / "rag_table_v22_modules"
MANIFEST = ROOT / "rag_table_v22_install_manifest.json"
NEW_MODULES = (
    "app/services/rag_table_extraction.py",
    "app/services/rag_pdf_table_recovery.py",
    "app/api/rag_table_routes.py",
    "app/api/rag_profile_routes.py",
)
BACKUP_TARGETS = (
    "app/services/analysis.py",
    "app/main.py",
) + NEW_MODULES

ANALYSIS_OLD = '''            selected = select_scientific_fragments(fragments, publication.domain, settings)
            provider = make_provider(settings)
            data = provider.extract(publication.domain, selected)'''
ANALYSIS_NEW = '''            selected = select_scientific_fragments(fragments, publication.domain, settings)
            # RAG v2.2: structurally linked table cells first, LLM only as fallback.
            # This is opt-out via RAG_TABLE_MODE=off; no change to Solar.
            if publication.domain == "rag" and os.getenv("RAG_TABLE_MODE", "prefer").lower() == "prefer":
                from app.services.rag_table_extraction import extract_rag_table_records
                from app.services.rag_pdf_table_recovery import recover_text_aligned_tables
                parsed_table = extract_rag_table_records(fragments)
                if not parsed_table.records:
                    pdf_path = settings.data_dir / "uploads" / f"{publication.id}.pdf"
                    if pdf_path.is_file():
                        recovered = recover_text_aligned_tables(
                            pdf_path.read_bytes(), max_pages=settings.max_pdf_pages)
                        seen_texts = {(f.page, f.text) for f in fragments}
                        next_pos = {}
                        for f in fragments:
                            next_pos[f.page] = max(next_pos.get(f.page, 0), f.position)
                        for table_frag in recovered:
                            if (table_frag.page, table_frag.text) in seen_texts:
                                continue
                            seen_texts.add((table_frag.page, table_frag.text))
                            page = table_frag.page
                            next_pos[page] = next_pos.get(page, 0) + 1
                            stored = SourceFragment(
                                id=str(uuid4()), publication_id=publication.id,
                                page=page, position=next_pos[page], text=table_frag.text,
                            )
                            db.add(stored)
                            fragments.append(stored)
                            publication.fragment_count += 1
                        if recovered:
                            db.flush()
                            parsed_table = extract_rag_table_records(fragments)
                if parsed_table.records:
                    data = {"records": parsed_table.records}
                    # The run has used no model; record true extraction provenance.
                    job.llm_mode = "table"
                    job.llm_model = "deterministic-pdf-table-v2.2"
                    # Grounding must know IDs of persisted table fragments.
                    selected = fragments
                else:
                    data = make_provider(settings).extract(publication.domain, selected)
            else:
                data = make_provider(settings).extract(publication.domain, selected)'''


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def patch_sources() -> dict[str, bytes]:
    required = ["app/services/analysis.py", "app/main.py", "app/api/rag_profile_routes.py"]
    for rel in required:
        if not (ROOT / rel).is_file():
            raise RuntimeError(f"Not the existing backend root (missing {rel}). Install from the dev.py folder.")
    replacements = {}
    analysis = (ROOT / "app/services/analysis.py").read_text(encoding="utf-8")
    if ANALYSIS_NEW in analysis:
        raise RuntimeError("RAG table v2.2 already appears installed. Use --check / --rollback.")
    if analysis.count(ANALYSIS_OLD) != 1:
        raise RuntimeError("analysis.py is different from the supported version. No files were changed.")
    analysis = analysis.replace(ANALYSIS_OLD, ANALYSIS_NEW)
    if "import os\n" not in analysis:
        if "import json\n" not in analysis:
            raise RuntimeError("Cannot find import insertion point in analysis.py")
        analysis = analysis.replace("import json\n", "import json\nimport os\n", 1)
    replacements["app/services/analysis.py"] = analysis.encode("utf-8")

    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    import_anchor = "from app.api.rag_profile_routes import router as rag_profile_router"
    include_anchor = "    app.include_router(rag_profile_router)"
    if main.count(import_anchor) != 1 or main.count(include_anchor) != 1:
        raise RuntimeError("main.py lacks expected RAG router anchors. No files were changed.")
    main = main.replace(import_anchor, import_anchor + "\nfrom app.api.rag_table_routes import router as rag_table_router", 1)
    main = main.replace(include_anchor, include_anchor + "\n    app.include_router(rag_table_router)", 1)
    replacements["app/main.py"] = main.encode("utf-8")

    audit = (ROOT / "app/api/rag_profile_routes.py").read_text(encoding="utf-8")
    if "def audit(" not in audit or "@router.get('/audit')" not in audit:
        raise RuntimeError("RAG audit route does not match v2.1 expected API. No files were changed.")
    for rel in NEW_MODULES:
        file = MODULE_ROOT / rel
        if not file.is_file():
            raise RuntimeError(f"Incomplete ZIP: missing {rel}")
        replacements[rel] = file.read_bytes()
    for rel, content in replacements.items():
        if rel.endswith(".py"):
            try:
                ast.parse(content.decode("utf-8"), filename=rel)
            except SyntaxError as exc:
                raise RuntimeError(f"Invalid Python in update {rel}: {exc}") from exc
    return replacements


def install() -> None:
    if MANIFEST.exists():
        raise RuntimeError("Installation manifest exists. Update already installed; use --check or --rollback.")
    replacements = patch_sources()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    planned = []
    for rel in BACKUP_TARGETS:
        target = ROOT / rel
        previous = target.read_bytes() if target.is_file() else None
        backup = target.with_name(target.name + f".before_rag_v22_{stamp}.bak") if previous is not None else None
        if backup is not None and backup.exists():
            raise RuntimeError(f"Backup path collision: {backup}")
        planned.append((rel, target, previous, backup, replacements[rel]))
    records = []
    try:
        for rel, target, previous, backup, content in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            if previous is not None:
                backup.write_bytes(previous)
            records.append({"file": rel, "backup": str(backup.relative_to(ROOT)) if backup else None,
                            "previous_sha256": sha(previous) if previous is not None else None,
                            "installed_sha256": sha(content)})
            temp = target.with_name(target.name + ".rag-v22.tmp")
            temp.write_bytes(content)
            temp.replace(target)
        MANIFEST.write_text(json.dumps({"version": "2.2", "files": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Do not leave a partially installed backend.
        for item in reversed(records):
            target = ROOT / item["file"]
            backup = ROOT / item["backup"] if item["backup"] else None
            if backup and backup.exists():
                shutil.copy2(backup, target)
            elif backup is None:
                target.unlink(missing_ok=True)
        raise
    print("INSTALLED RAG Table v2.2; backups are retained; SQLite and .env untouched")
    print("Run: python3.11 -m pytest -q")
    print("Then: python3.11 dev.py run")


def rollback() -> None:
    if not MANIFEST.is_file():
        raise RuntimeError("No RAG v2.2 manifest found; nothing to rollback.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        target = ROOT / item["file"]
        if not target.is_file() or sha(target.read_bytes()) != item["installed_sha256"]:
            raise RuntimeError(f"File modified after installation: {item['file']}. Rollback halted to protect changes.")
        if item["backup"] and not (ROOT / item["backup"]).is_file():
            raise RuntimeError(f"Missing backup {item['backup']}. Rollback halted.")
    for item in manifest["files"]:
        target = ROOT / item["file"]
        backup = ROOT / item["backup"] if item["backup"] else None
        if backup:
            shutil.copy2(backup, target)
        else:
            target.unlink()
    MANIFEST.unlink()
    print("ROLLED BACK code only; SQLite and uploaded PDF files untouched")


def check() -> None:
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = ROOT / item["file"]
            assert path.is_file() and sha(path.read_bytes()) == item["installed_sha256"], item["file"]
        print("OK: RAG v2.2 installed and code files match manifest")
    else:
        prepared = patch_sources()
        print(f"OK: compatible backend; {len(prepared)} code files will be updated; no DB schema changes")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    opts = cli.parse_args()
    try:
        if opts.check:
            check()
        elif opts.rollback:
            rollback()
        else:
            install()
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
