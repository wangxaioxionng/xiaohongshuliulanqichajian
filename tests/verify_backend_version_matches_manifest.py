import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    manifest = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
    app_py = (ROOT / "server/app.py").read_text(encoding="utf-8")
    match = re.search(r'FastAPI\(title="xhs-collect API", version="([^"]+)"\)', app_py)
    if not match:
        raise AssertionError("server FastAPI version declaration not found")
    if match.group(1) != manifest["version"]:
        raise AssertionError(
            f"backend version {match.group(1)} does not match manifest {manifest['version']}"
        )


if __name__ == "__main__":
    main()
