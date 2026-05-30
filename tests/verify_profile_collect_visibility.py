from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> None:
    popup = read("extension/popup.js")
    background = read("extension/background.js")
    backend = read("server/app.py")

    assert_contains(
        background,
        'PROFILE_COLLECT_STATE_KEY',
        "persistent profile collect state in background",
    )
    assert_contains(
        background,
        'profile_collect_start',
        "background start message for profile collection",
    )
    assert_contains(
        background,
        'profile_collect_links_done',
        "page-to-background link extraction completion message",
    )
    assert_contains(
        popup,
        'profile_collect_state',
        "popup can render background progress state",
    )
    assert_contains(
        popup,
        'profile_collect_get_state',
        "popup can recover progress after reopening",
    )
    assert_contains(
        backend,
        'phase="playlist_extract"',
        "backend playlist extraction phase",
    )
    assert_contains(
        backend,
        'phase="feishu_prepare"',
        "backend Feishu sheet creation/check phase",
    )
    assert_contains(
        backend,
        'phase="feishu_write"',
        "backend Feishu write phase",
    )


if __name__ == "__main__":
    main()
