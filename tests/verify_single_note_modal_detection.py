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
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")
    required = [
        ("normalizeXhsNoteUrl", "single-note URL normalizer"),
        ("extractActiveNoteUrlFromPage", "visible note modal extractor"),
        ("resolveCurrentNoteUrl", "popup note resolver"),
        ("resolvedNoteUrl", "shared resolved note URL state"),
    ]
    for needle, label in required:
        if needle not in popup:
            raise AssertionError(f"missing {label}: {needle}")

    init_pos = popup.find("async function init()")
    profile_pos = popup.find("XHS_PROFILE_RE.test(url)", init_pos)
    resolve_pos = popup.find("resolveCurrentNoteUrl", init_pos)
    if not (init_pos >= 0 and resolve_pos >= 0 and profile_pos >= 0 and resolve_pos < profile_pos):
        raise AssertionError("init must resolve active note before profile-page branch")

    handle = extract_function(popup, "handleCollect")
    if "normalizeXhsNoteUrl" not in handle or "resolvedNoteUrl" not in handle:
        raise AssertionError("handleCollect must submit the resolved active note URL")

    helper = extract_function(popup, "normalizeXhsNoteUrl")
    js = f"""
{helper}
const ok = normalizeXhsNoteUrl("https://www.xiaohongshu.com/explore/abc123?xsec_token=t#comment");
if (ok !== "https://www.xiaohongshu.com/explore/abc123?xsec_token=t") {{
  throw new Error("note URL normalization failed: " + ok);
}}
const badProfile = normalizeXhsNoteUrl("https://www.xiaohongshu.com/user/profile/user1?xsec_token=t");
if (badProfile !== "") throw new Error("profile URL must not be treated as a note URL");
const badFeed = normalizeXhsNoteUrl("https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend");
if (badFeed !== "") throw new Error("feed URL must not be treated as a note URL");
"""
    result = subprocess.run(
        ["node", "-e", js],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    main()
