#!/usr/bin/env python3
"""One development entry point for macOS, Windows, and Linux (stdlib-only).

macOS:   python3.11 dev.py setup && python3.11 dev.py run
Windows: py -3.11 dev.py setup && py -3.11 dev.py run

Never copy .venv across operating systems. Recreate it with 'setup'.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def call(*args: str) -> None:
    print("\n$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def ensure_supported_python() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit(
            f"Python {sys.version.split()[0]} is too old. Install Python 3.11 or 3.12 "
            "on both macOS and Windows."
        )
    print(f"Python: {sys.version.split()[0]}; OS: {sys.platform}; project: {ROOT}")


def need_venv() -> None:
    if not VENV_PY.is_file():
        raise SystemExit("Virtual environment is missing. Run: python dev.py setup")


def setup(skip_tests: bool = False) -> None:
    if not VENV_PY.exists():
        print(f"Creating virtual environment at: {VENV}")
        venv.EnvBuilder(with_pip=True).create(VENV)
    call(str(VENV_PY), "-m", "pip", "install", "-r", "requirements-dev.txt")
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        print("Created .env with LLM_MODE=mock. Do not commit API keys.")
    else:
        print("Existing .env preserved.")
    if not skip_tests:
        call(str(VENV_PY), "-m", "pytest", "-q")
    print("\nReady! Start with: python dev.py run")


def run(host: str, port: int) -> None:
    need_venv()
    print(f"Open http://127.0.0.1:{port}/docs after the server starts")
    call(str(VENV_PY), "-m", "uvicorn", "app.main:app", "--reload", "--host", host, "--port", str(port))


def test() -> None:
    need_venv()
    call(str(VENV_PY), "-m", "pytest", "-q")


def demo() -> None:
    need_venv()
    call(str(VENV_PY), "scripts/generate_demo_pdfs.py")


def main() -> None:
    ensure_supported_python()
    parser = argparse.ArgumentParser(description="The Scientific Arbitrator: cross-platform dev commands")
    sub = parser.add_subparsers(dest="command", required=True)
    setup_p = sub.add_parser("setup", help="Create .venv, install deps, create .env, run tests")
    setup_p.add_argument("--skip-tests", action="store_true")
    run_p = sub.add_parser("run", help="Start local FastAPI server")
    run_p.add_argument("--host", default="127.0.0.1")
    run_p.add_argument("--port", type=int, default=8000)
    sub.add_parser("test", help="Run automated tests")
    sub.add_parser("demo", help="Regenerate synthetic PDF examples")
    args = parser.parse_args()
    if args.command == "setup":
        setup(skip_tests=args.skip_tests)
    elif args.command == "run":
        run(args.host, args.port)
    elif args.command == "test":
        test()
    elif args.command == "demo":
        demo()


if __name__ == "__main__":
    main()
