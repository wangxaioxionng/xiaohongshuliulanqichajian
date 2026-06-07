from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    html = (ROOT / "extension/popup.html").read_text(encoding="utf-8")
    popup = (ROOT / "extension/popup.js").read_text(encoding="utf-8")
    background = (ROOT / "extension/background.js").read_text(encoding="utf-8")
    server = (ROOT / "server/app.py").read_text(encoding="utf-8")

    card_start = html.find('id="account-lib-card"')
    actions_start = html.find('class="al-actions"', card_start)
    if card_start < 0 or actions_start < 0:
        raise AssertionError("account homepage card or action area missing")
    card_before_actions = html[card_start:actions_start]
    if 'id="profile-note-input"' not in card_before_actions:
        raise AssertionError("account card must expose a shared remark input before actions")

    if "function getProfileAccountNote()" not in popup:
        raise AssertionError("popup must have a shared helper for account-card remark")

    if 'document.getElementById("al-note-input").value = getProfileAccountNote();' not in popup:
        raise AssertionError("account library modal must inherit the account-card remark")

    if "note: getProfileAccountNote()," not in popup:
        raise AssertionError("profile collect start payload must carry the account-card remark")

    if 'note: (payload.note || "").trim(),' not in background:
        raise AssertionError("background task state must keep the account-card remark")

    if 'note: state.note || "",' not in background:
        raise AssertionError("profile collect backend request must receive the account-card remark")

    profile_request_start = server.find("class ProfileCollectRequest")
    shop_request_start = server.find("class ShopProductsCollectRequest")
    if profile_request_start < 0 or shop_request_start < 0:
        raise AssertionError("profile collect request model missing")
    profile_request_body = server[profile_request_start:shop_request_start]
    if 'note: Optional[str] = ""' not in profile_request_body:
        raise AssertionError("profile collect API model must accept the account-card remark")


if __name__ == "__main__":
    main()
