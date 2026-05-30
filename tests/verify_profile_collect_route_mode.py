import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"


def main() -> None:
    sys.path.insert(0, str(SERVER))
    fake_jwt = types.SimpleNamespace(
        InvalidTokenError=Exception,
        ExpiredSignatureError=Exception,
        encode=lambda payload, secret, algorithm=None: "fake.jwt.token",
        decode=lambda token, secret, algorithms=None: {},
    )
    sys.modules.setdefault("jwt", fake_jwt)
    app = importlib.import_module("app")

    app.auth.require_active_with_sheet = lambda authorization=None, x_auth_token=None: {
        "user_id": "test-user",
        "spreadsheet_token": "fake-token",
    }

    calls = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            calls.append((self.target.__name__, self.args))

    app.threading.Thread = FakeThread

    single_resp = app.profile_collect(app.ProfileCollectRequest(
        profile_url="https://www.xiaohongshu.com/user/profile/user1",
        account_name="测试账号",
        note_urls=[
            "https://www.xiaohongshu.com/explore/note1?xsec_token=t1&xsec_source=pc_user",
            "https://www.xiaohongshu.com/explore/note1",
        ],
        max_items=400,
    ))
    assert single_resp["collect_mode"] == "single_post"
    assert single_resp["total"] == 1
    assert calls[-1][0] == "_run_profile_collect_task"

    playlist_resp = app.profile_collect(app.ProfileCollectRequest(
        profile_url="https://www.xiaohongshu.com/user/profile/user1",
        account_name="测试账号",
        note_urls=[],
        max_items=400,
    ))
    assert playlist_resp["collect_mode"] == "playlist"
    assert playlist_resp["total"] == 400
    assert calls[-1][0] == "_run_profile_collect_playlist_task"


if __name__ == "__main__":
    main()
