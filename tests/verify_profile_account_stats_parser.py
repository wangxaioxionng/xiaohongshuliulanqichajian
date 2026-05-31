import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")
    popup_html = (ROOT / "extension/popup.html").read_text(encoding="utf-8")
    if "findNumNear" in popup:
        raise AssertionError("old ambiguous findNumNear parser still exists")
    if 'id="al-detected-likes"' not in popup_html:
        raise AssertionError("popup account card must show likes_count separately")
    start = popup.find("function parseProfileStatsFromText(bodyText)")
    if start < 0:
        raise AssertionError("missing parseProfileStatsFromText(bodyText)")
    end = popup.find("\nfunction extractAccountInfoFromPage", start)
    if end < 0:
        raise AssertionError("parseProfileStatsFromText must be before extractAccountInfoFromPage")

    helper = popup[start:end]
    js = f"""
{helper}
const cases = [
  {{
    text: "19 关注 5388 粉丝 7.1万 获赞与收藏",
    expected: {{ follow_count: "19", fans_count: "5388", likes_count: "7.1万" }},
  }},
  {{
    text: "圆圆blue 小红书号 Qiqi1101 161/49kg 19 关注 5388 粉丝 7.1万 获赞与收藏 业务合作",
    expected: {{ follow_count: "19", fans_count: "5388", likes_count: "7.1万" }},
  }},
  {{
    text: "19\\n关注\\n5388\\n粉丝\\n7.1万\\n获赞与收藏",
    expected: {{ follow_count: "19", fans_count: "5388", likes_count: "7.1万" }},
  }},
  {{
    text: "笔记 48 粉丝 2.3万 获赞与收藏 11.8万",
    expected: {{ notes_count: "48", fans_count: "2.3万", likes_count: "11.8万" }},
  }},
  {{
    text: "55 关注 208 粉丝 2148 获赞与收藏 笔记・33 专辑・0",
    expected: {{ follow_count: "55", fans_count: "208", likes_count: "2148", notes_count: "33" }},
  }},
];
for (const item of cases) {{
  const got = parseProfileStatsFromText(item.text);
  for (const [key, value] of Object.entries(item.expected)) {{
    if (got[key] !== value) {{
      throw new Error(`${{key}} expected ${{value}} got ${{got[key] || ""}} for ${{JSON.stringify(item.text)}}`);
    }}
  }}
}}
console.log(JSON.stringify(cases.map((item) => parseProfileStatsFromText(item.text))));
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
    parsed = json.loads(result.stdout)
    assert parsed[0]["fans_count"] == "5388"
    assert parsed[0]["likes_count"] == "7.1万"


if __name__ == "__main__":
    main()
