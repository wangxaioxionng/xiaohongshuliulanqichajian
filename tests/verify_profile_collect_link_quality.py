import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def extract_function(source: str, name: str) -> str:
    start = source.find(f"function {name}(")
    if start < 0:
        raise AssertionError(f"missing function {name}")
    depth = 0
    body_started = False
    for idx in range(start, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
            body_started = True
        elif char == "}":
            depth -= 1
            if body_started and depth == 0:
                return source[start:idx + 1]
    raise AssertionError(f"function {name} not closed")


def main() -> None:
    background = (ROOT / "extension/background.js").read_text(encoding="utf-8")
    for needle, label in [
        ("noteUrlHasXsecToken", "xsec_token readiness helper"),
        ("filterApiReadyNoteUrls", "API-ready link filter"),
        ("window.__INITIAL_STATE__", "XHS page state extraction"),
        ("xsecToken", "xsec token extraction from page state"),
        ("主页批量接口", "profile playlist API fallback"),
        ("a.href", "use resolved anchor href candidate"),
        ("api_ready_count", "visible API-ready link count"),
    ]:
        if needle not in background:
            raise AssertionError(f"missing {label}: {needle}")
    if "submitProfileCollectToBackend" not in background:
        raise AssertionError("profile collection must submit to backend playlist API even when links are short")

    helper_names = [
        "noteIdFromXhsUrl",
        "noteUrlHasXsecToken",
        "dedupeNoteUrlsPreferFull",
        "filterApiReadyNoteUrls",
    ]
    helpers = "\n".join(extract_function(background, name) for name in helper_names)
    js = f"""
const PROFILE_COLLECT_LIMIT = 400;
{helpers}
const links = [
  "https://www.xiaohongshu.com/explore/abc123",
  "https://www.xiaohongshu.com/explore/abc123?xsec_token=fresh-token&xsec_source=pc_user",
  "https://www.xiaohongshu.com/explore/def456",
];
const deduped = dedupeNoteUrlsPreferFull(links, 400);
const ready = filterApiReadyNoteUrls(links, 400);
if (deduped[0].indexOf("xsec_token=fresh-token") === -1) {{
  throw new Error("dedupe did not prefer full token link");
}}
if (ready.length !== 1 || ready[0].indexOf("abc123") === -1) {{
  throw new Error("API-ready filter must reject short tokenless links");
}}
console.log(JSON.stringify({{ deduped, ready }}));
"""
    result = subprocess.run(
        ["node", "-e", js],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
      raise AssertionError(result.stderr.strip() or result.stdout.strip())
    parsed = json.loads(result.stdout)
    assert len(parsed["ready"]) == 1


if __name__ == "__main__":
    main()
