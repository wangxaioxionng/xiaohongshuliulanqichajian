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
    extract_account = extract_function(popup, "extractAccountInfoFromPage")
    js = f"""
{extract_account}

global.location = {{
  href: "https://www.xiaohongshu.com/user/profile/61e44e300000000002024f47?xsec_token=t",
}};
global.window = {{
  __INITIAL_STATE__: {{
    user: {{
      userPageData: {{
        interactions: [
          {{ type: "follows", name: "关注", count: "55", i18nCount: "55" }},
          {{ type: "fans", name: "粉丝", count: "208", i18nCount: "208" }},
          {{ type: "interaction", name: "获赞与收藏", count: "2148", i18nCount: "2.1K" }},
        ],
        tabPublic: {{
          collectionNote: {{ count: 33, display: true, lock: false }},
        }},
        basicInfo: {{
          nickname: "长乐宫宫主",
          redId: "6560933152",
          ipLocation: "北京",
          desc: "文艺博主\\n书画方向",
        }},
      }},
    }},
  }},
}};
global.document = {{
  title: "加载中 - 小红书",
  body: {{ innerText: "" }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};

const data = extractAccountInfoFromPage();
const expected = {{
  account_name: "长乐宫宫主",
  xhs_id: "6560933152",
  follow_count: "55",
  fans_count: "208",
  likes_count: "2148",
  notes_count: "33",
  ip_location: "北京",
  bio: "文艺博主\\n书画方向",
}};
for (const [key, value] of Object.entries(expected)) {{
  if (data[key] !== value) {{
    throw new Error(`${{key}} expected ${{value}} got ${{data[key] || ""}}`);
  }}
}}
"""
    result = subprocess.run(
        ["node", "-e", js],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    main()
