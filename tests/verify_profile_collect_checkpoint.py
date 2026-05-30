from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> None:
    background = read("extension/background.js")
    popup = read("extension/popup.js")
    backend = read("server/app.py")

    assert_contains(
        background,
        "PROFILE_COLLECT_CHECKPOINTS_KEY",
        "persistent profile link checkpoints in background",
    )
    assert_contains(
        background,
        "PROFILE_COLLECT_CHECKPOINT_BATCH_SIZE = 80",
        "80-link checkpoint batch size",
    )
    assert_contains(
        background,
        "profile_collect_link_checkpoint",
        "page-to-background checkpoint message",
    )
    assert_contains(
        background,
        "existingNoteUrls",
        "resume extraction from previously saved links",
    )
    assert_contains(
        background,
        "saveProfileCheckpoint",
        "checkpoint storage writer",
    )
    assert_contains(
        background,
        "checkpoint_saved",
        "visible saved-link count in state",
    )
    assert_contains(
        popup,
        "已保存",
        "popup shows saved checkpoint count",
    )
    assert_contains(
        backend,
        "_append_profile_record_immediately",
        "backend writes successful notes incrementally",
    )
    assert_contains(
        backend,
        "partial_saved",
        "backend reports partially saved records",
    )


if __name__ == "__main__":
    main()
