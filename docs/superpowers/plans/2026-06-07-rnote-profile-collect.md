# Rnote Profile Collect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the account full-collection API path with Rnote so profile note lists and note details are fetched through the new API provider.

**Architecture:** Keep the browser extension flow unchanged. Add a backend API-provider adapter that maps Rnote responses into the existing profile collection record shape, so Feishu writing, failure rows, retry, progress display, packaging, and deployment stay on the existing path.

**Tech Stack:** Python FastAPI backend, requests, existing Chrome extension, existing release quality tests.

---

### Task 1: Rnote Adapter Tests

**Files:**
- Create: `tests/verify_rnote_profile_collect_backend.py`
- Modify: `tests/run_release_quality.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:
- `profile_collect_api_provider=rnote` selects Rnote endpoints.
- `_fetch_profile_posts()` maps `/api/v2/crawler/user/posted` notes into existing post fields.
- `_fetch_note_post()` maps `/api/v2/crawler/note/image` into existing single-note fields.
- Profile URLs expose the user ID needed by Rnote.

- [ ] **Step 2: Run tests and confirm failure**

Run: `python3 tests/verify_rnote_profile_collect_backend.py`

Expected before implementation: FAIL because Rnote provider helpers do not exist.

### Task 2: Backend Rnote Adapter

**Files:**
- Modify: `server/app.py`
- Modify: `server/config.json.example`

- [ ] **Step 1: Implement minimal provider config**

Add:
- `PROFILE_COLLECT_API_PROVIDER`
- `RNOTE_API_BASE`
- `RNOTE_API_KEY` lookup via `rnote_api_key` or existing `profile_collect_api_key`

- [ ] **Step 2: Implement Rnote response mapping**

Add helpers that:
- Extract `user_id` from `/user/profile/<id>`.
- Call `/api/v2/crawler/user/posted` with `user_id`, `cursor`, `num`.
- Call `/api/v2/crawler/note/image` with `note_id`.
- Normalize Rnote nested data to existing `title/text/medias/created_at/post_url` fields.
- Preserve current Meowload behavior when provider is not `rnote`.

- [ ] **Step 3: Run focused tests**

Run: `python3 tests/verify_rnote_profile_collect_backend.py`

Expected after implementation: PASS.

### Task 3: Release Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `extension/manifest.json` through release script

- [ ] **Step 1: Run full quality checks**

Run: `python3 tests/run_release_quality.py`

Expected: all checks PASS.

- [ ] **Step 2: Package**

Run: `./bump-version.sh patch`

Expected: new `dist/小红书一键收录-vX.Y.Z.zip` is created and does not include secrets.

- [ ] **Step 3: Deploy backend**

Backup remote backend files, copy changed backend files, restart only `xhs-collect-api`, verify `/api/health`.

- [ ] **Step 4: Commit and push**

Commit code, tests, changelog, plan file, and push the current branch.
