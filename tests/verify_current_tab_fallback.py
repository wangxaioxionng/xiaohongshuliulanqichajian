import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def extract_function(source: str, name: str) -> str:
    start = source.find(f"function {name}(")
    if start < 0:
        raise AssertionError(f"missing function {name}")
    async_start = source.rfind("async ", 0, start)
    if async_start >= 0 and source[async_start:start].strip() == "async":
        start = async_start
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
    helper = extract_function(popup, "getCurrentTab")
    js = f"""
const XHS_HOST_RE = /(?:xiaohongshu\\.com|xhslink\\.com)/i;
{helper}

let calls = [];
global.chrome = {{
  tabs: {{
    query(query, cb) {{
      calls.push(query);
      if (query.currentWindow) {{
        cb([{{ url: "https://chatgpt.com/", title: "ChatGPT" }}]);
        return;
      }}
      if (query.lastFocusedWindow) {{
        cb([{{ url: "https://www.xiaohongshu.com/explore/abc123?xsec_token=t", title: "小红书" }}]);
        return;
      }}
      cb([]);
    }}
  }}
}};

getCurrentTab().then((tab) => {{
  if (!/xiaohongshu\\.com/.test(tab.url || "")) {{
    throw new Error("should fall back to the focused Xiaohongshu tab, got: " + (tab.url || ""));
  }}
  if (!calls.some((q) => q.lastFocusedWindow)) {{
    throw new Error("missing lastFocusedWindow fallback query");
  }}
}}).catch((err) => {{
  console.error(err.message || err);
  process.exit(1);
}});
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
