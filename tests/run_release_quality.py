import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CHECKS = [
    ("当前标签页识别", ["python3", "tests/verify_current_tab_fallback.py"]),
    ("账号主页文本兜底", ["python3", "tests/verify_profile_account_text_fallback.py"]),
    ("账号主页状态兜底", ["python3", "tests/verify_profile_account_initial_state.py"]),
    ("账号统计解析", ["python3", "tests/verify_profile_account_stats_parser.py"]),
    ("笔记浮层识别", ["python3", "tests/verify_single_note_modal_detection.py"]),
    ("主页链接质量", ["python3", "tests/verify_profile_collect_link_quality.py"]),
    ("主页采集进度展示", ["python3", "tests/verify_profile_collect_visibility.py"]),
    ("主页采集断点续采", ["python3", "tests/verify_profile_collect_checkpoint.py"]),
    ("主页采集增量后端", ["python3", "tests/verify_profile_collect_incremental_backend.py"]),
    ("主页采集临时失败重试", ["python3", "tests/verify_profile_collect_retry_backend.py"]),
    ("主页采集失败落表补采", ["python3", "tests/verify_profile_collect_failure_backfill_backend.py"]),
    ("主页采集路由模式", ["python3", "tests/verify_profile_collect_route_mode.py"]),
    ("主页批量接口后端", ["python3", "tests/verify_profile_collect_playlist_backend.py"]),
    ("主页采集图片嵌入", ["python3", "tests/verify_profile_collect_image_embedding.py"]),
    ("店铺商品与评论原型", ["python3", "tests/verify_shop_comments_prototype.py"]),
    ("店铺商品写表后端", ["python3", "tests/verify_shop_products_sheet_backend.py"]),
    ("popup 脚本语法", ["node", "--check", "extension/popup.js"]),
    ("background 脚本语法", ["node", "--check", "extension/background.js"]),
    ("commerce probe 脚本语法", ["node", "--check", "extension/xhs_commerce_probe.js"]),
    ("manifest JSON", ["python3", "-m", "json.tool", "extension/manifest.json"]),
    ("后台 Python 语法", ["python3", "-m", "py_compile", "server/app.py", "server/lark_writer.py", "server/auth.py", "server/db.py"]),
]


def run_check(name: str, cmd: list[str]) -> bool:
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if result.returncode == 0:
        print(f"PASS {name}")
        return True
    print(f"FAIL {name}")
    output = (result.stdout + "\n" + result.stderr).strip()
    if output:
        print(output)
    return False


def scan_latest_zip() -> bool:
    zips = sorted((ROOT / "dist").glob("小红书一键收录-v*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        print("SKIP 打包敏感文件扫描：未找到 zip")
        return True
    latest = zips[-1]
    blocked = []
    with zipfile.ZipFile(latest) as zf:
        for name in zf.namelist():
            parts = name.split("/")
            if any(part in {"secrets.js", "config.json", "data.db"} for part in parts):
                blocked.append(name)
            if ".spec-workflow" in parts:
                blocked.append(name)
    if blocked:
        print(f"FAIL 打包敏感文件扫描：{latest.name}")
        for name in blocked:
            print(name)
        return False
    print(f"PASS 打包敏感文件扫描：{latest.name}")
    return True


def main() -> int:
    ok = True
    for name, cmd in CHECKS:
        ok = run_check(name, cmd) and ok
    ok = scan_latest_zip() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
