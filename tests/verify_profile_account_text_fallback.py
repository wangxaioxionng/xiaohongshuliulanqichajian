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
    parse_stats = extract_function(popup, "parseProfileStatsFromText")
    extract_account = extract_function(popup, "extractAccountInfoFromPage")
    js = f"""
{parse_stats}
{extract_account}

const profileText = `圆圆blue
小红书号：Qiqi1101 IP属地：浙江
161/49kg 专注于发现美丽的事物。
19 关注 5388 粉丝 7.1万 获赞与收藏
笔记 收藏`;

global.location = {{ href: "https://www.xiaohongshu.com/user/profile/abc123" }};
global.document = {{
  title: "圆圆blue - 小红书",
  body: {{ innerText: profileText }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};

const data = extractAccountInfoFromPage();
if (data.account_name !== "圆圆blue") {{
  throw new Error("account name fallback failed: " + data.account_name);
}}
if (data.xhs_id !== "Qiqi1101") {{
  throw new Error("xhs id parse failed: " + data.xhs_id);
}}
if (data.fans_count !== "5388") {{
  throw new Error("fans parse failed: " + data.fans_count);
}}
if (data.likes_count !== "7.1万") {{
  throw new Error("likes parse failed: " + data.likes_count);
}}
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

