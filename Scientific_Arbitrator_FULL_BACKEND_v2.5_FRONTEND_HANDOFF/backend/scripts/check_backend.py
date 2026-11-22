"""Cross-platform smoke check (stdlib only): python scripts/check_backend.py [base_url]."""
import json
import sys
from urllib.request import urlopen
from urllib.error import URLError

base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
checks = ["/api/v1/health", "/api/v1/domains", "/openapi.json", "/api/v1/documents"]
try:
    for route in checks:
        with urlopen(base + route, timeout=10) as reply:
            data = json.loads(reply.read().decode("utf-8"))
            assert reply.status == 200
            if route == "/openapi.json":
                for expected in (
                    "/api/v1/scientific/compare",
                    "/api/v1/scientific/search",
                    "/api/v1/scientific/quality/{publication_id}",
                    "/api/v1/scientific/reports/{publication_id}",
                ):
                    assert expected in data["paths"], f"Missing API path: {expected}"
            print("OK", route)
except (URLError, AssertionError, OSError, ValueError) as exc:
    print("FAILED:", exc)
    sys.exit(1)
print("All smoke checks passed. No LLM requests were sent.")
