"""Write the FastAPI OpenAPI schema to ``web/openapi.json`` (the web's API types come from it).

uv run python scripts/export_openapi.py          # write
uv run python scripts/export_openapi.py --check  # exit 1 if the committed file is stale
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

OUT = ROOT / "web" / "openapi.json"


def main() -> int:
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != schema:
            print(f"{OUT.relative_to(ROOT)} is stale: run uv run python scripts/export_openapi.py")
            return 1
        return 0
    OUT.write_text(schema, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
