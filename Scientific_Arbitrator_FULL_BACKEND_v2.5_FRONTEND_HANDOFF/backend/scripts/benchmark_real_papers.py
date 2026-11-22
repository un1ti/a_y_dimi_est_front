#!/usr/bin/env python3
"""Run one REAL Solar PDF and one REAL RAG PDF through a running backend.

Works on macOS and Windows. Requires a working network and LLM API key.
No results are invented. Manual PDFs can be provided with --solar and --rag.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

import httpx

ROOT = Path(__file__).resolve().parents[1]
PAPERS_DIR = ROOT / "data" / "real_papers"
REPORTS_DIR = ROOT / "reports"

PAPERS = {
    "solar": {
        "filename": "solar_yu_2024.pdf",
        "title": "Yu et al. (2024), Additive engineering for efficient wide-bandgap perovskite solar cells",
        "url": "https://www.frontiersin.org/journals/chemistry/articles/10.3389/fchem.2024.1441057/pdf",
        "doi": "10.3389/fchem.2024.1441057",
        "ground_truth": {
            "control": {"pce_pct": 18.51, "voc_v": 1.170, "jsc_ma_cm2": 20.18, "ff_pct": 78.38},
            "modified": {"pce_pct": 21.50, "voc_v": 1.193, "jsc_ma_cm2": 22.59, "ff_pct": 79.80},
        },
    },
    "rag": {
        "filename": "rag_lewis_2020.pdf",
        "title": "Lewis et al. (2020), Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "url": "https://papers.neurips.cc/paper_files/paper/2020/file/6b493230205f780e1bc26945df7481e5-Paper.pdf",
        "ground_truth": {
            "RAG-Sequence / NQ / Exact Match": 44.5,
            "RAG-Token / NQ / Exact Match": 44.1,
        },
    },
}


def download_pdf(url: str, path: Path) -> Path:
    print(f"Downloading: {url}", flush=True)
    request = Request(url, headers={"User-Agent": "ScientificArbitrator-evaluation/0.1"})
    try:
        with urlopen(request, timeout=35) as response:
            data = response.read(25 * 1024 * 1024 + 1)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot download {url}: {type(exc).__name__}. "
            f"Download the paper in your browser and place it at {path}"
        ) from exc
    if len(data) > 25 * 1024 * 1024 or not data.startswith(b"%PDF-"):
        raise RuntimeError("Response is not a valid PDF or is larger than 25 MB")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def get_pdf(domain: str, override: str | None, skip_download: bool) -> Path:
    path = Path(override).expanduser() if override else PAPERS_DIR / PAPERS[domain]["filename"]
    if path.is_file():
        return path
    if skip_download:
        raise RuntimeError(f"Missing PDF: {path}. Download it from {PAPERS[domain]['url']}")
    return download_pdf(PAPERS[domain]["url"], path)


def near(value: object, expected: float) -> bool:
    try:
        return abs(float(value) - expected) <= max(.025, abs(expected) * .001)
    except (ValueError, TypeError):
        return False


def solar_check(records: list[dict]) -> dict:
    checks = {}
    for group, vals in PAPERS["solar"]["ground_truth"].items():
        candidates = [r for r in records if all(near(r["data"].get(key), val) for key, val in vals.items())]
        checks[group + "_same_record"] = bool(candidates and candidates[0]["evidence"])
    return checks


def rag_check(records: list[dict]) -> dict:
    checks = {}
    for variant, expected in (("sequence", 44.5), ("token", 44.1)):
        found = False
        for row in records:
            data = row["data"]
            label = (str(data.get("rag_variant") or "") + " " + str(data.get("config_label") or "")).lower()
            dataset = str(data.get("dataset_name") or "").lower()
            metric = str(data.get("metric_name") or "").lower()
            variant_ok = ("sequence" in label or "rag-seq" in label) if variant == "sequence" else "token" in label
            if variant_ok and ("nq" in dataset or "natural questions" in dataset) and ("exact match" in metric or metric == "em") and near(data.get("metric_value"), expected) and row["evidence"]:
                found = True
                break
        checks[f"RAG-{variant}_NQ_EM"] = found
    return checks


def analyze(client: httpx.Client, root_url: str, domain: str, path: Path, timeout_s: int) -> dict:
    endpoint = root_url.rstrip("/") + "/api/v1"
    print(f"\n=== {domain.upper()} | {path.name} ===", flush=True)
    with path.open("rb") as file:
        response = client.post(f"{endpoint}/documents", data={"domain": domain}, files={"file": (path.name, file, "application/pdf")})
    response.raise_for_status()
    doc = response.json()
    print(f"Uploaded/registered: {doc['id']} | pages={doc['page_count']} | fragments={doc['fragment_count']}")
    response = client.post(f"{endpoint}/documents/{doc['id']}/analyze")
    response.raise_for_status()
    job_id = response.json()["id"]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"{endpoint}/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"Timed out waiting for job {job_id}. Check /docs and server logs")
    if job["status"] != "done":
        raise RuntimeError(f"Extraction failed: {job.get('error')} (job {job_id})")
    response = client.get(f"{endpoint}/documents/{doc['id']}/results")
    response.raise_for_status()
    records = response.json()["records"]
    checks = solar_check(records) if domain == "solar" else rag_check(records)
    print(f"Records: {len(records)} | verified evidence links: {sum(len(x['evidence']) for x in records)}")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'REVIEW'}: {name}")
    return {"publication": PAPERS[domain]["title"], "original_pdf": PAPERS[domain]["url"], "document": doc, "job": job, "checks": checks, "records": records}


def main():
    parser = argparse.ArgumentParser(description="Evaluation on one real PDF from each domain")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--solar", help="Path to Solar PDF previously downloaded in browser")
    parser.add_argument("--rag", help="Path to RAG PDF previously downloaded in browser")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    results = {}
    with httpx.Client(timeout=150) as client:
        response = client.get(args.base_url.rstrip("/") + "/api/v1/llm/status")
        response.raise_for_status()
        llm = response.json()
        if llm["mode"] != "openai" or not llm["configured"]:
            raise RuntimeError(f"Real LLM not configured on server. Current status: {llm}. Set LLM_MODE=openai, LLM_MODEL, LLM_API_KEY in .env and restart")
        for domain in ("solar", "rag"):
            path = get_pdf(domain, getattr(args, domain), args.no_download)
            results[domain] = analyze(client, args.base_url, domain, path, args.timeout)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "real_papers_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved to {report_path}")
    if all(all(v for v in result["checks"].values()) for result in results.values()):
        print("All 4 selected anchor checks PASSED. Scientific validation is still separate.")
        return 0
    print("Some anchor checks need review. Inspect the JSON report and cited fragments.")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
