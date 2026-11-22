"""Run the supplied FastAPI app on a private loopback port for the Node server."""
from pathlib import Path
import os
import socket
import sys
import threading

backend = Path(__file__).resolve().parent / "Scientific_Arbitrator_FULL_BACKEND_v2.5_FRONTEND_HANDOFF" / "backend"
sys.path.insert(0, str(backend))

import uvicorn
from app import config  # Load backend/.env before applying the site's upload default.
os.environ.setdefault("MAX_UPLOAD_MB", "64")
# The site uses the bundled table extractor and its local regex fallback only.
os.environ["RAG_TABLE_MODE"] = "prefer"
os.environ["LLM_MODE"] = "mock"
from app.main import app

# Closing the Node server (including VS Code Stop) also closes its stdin pipe.
def stop_with_parent():
    sys.stdin.buffer.read()
    os._exit(0)

threading.Thread(target=stop_with_parent, daemon=True).start()
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    print(f"RAG_PORT={listener.getsockname()[1]}", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])
