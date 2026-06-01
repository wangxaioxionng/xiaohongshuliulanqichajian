# Profile Failure Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Account profile collection must save failed note links into the Feishu profile sheet, then automatically retry those failed rows and overwrite rows that later succeed.

**Architecture:** Keep the existing single background task. First pass writes successes immediately and also appends final failures to the same `XX全采集` sheet. A second pass retries those failed rows; successful retries overwrite the original failed row, and final failures remain visible with the reason.

**Tech Stack:** Python FastAPI backend, `LarkWriter` Feishu sheet writer, Chrome extension popup/background JavaScript, existing script-style Python tests.

---

### Task 1: Backend Failure Rows and Retry Pass

**Files:**
- Modify: `server/lark_writer.py`
- Modify: `server/app.py`
- Test: `tests/verify_profile_collect_failure_backfill_backend.py`
- Modify: `tests/run_release_quality.py`

- [ ] Write a failing test where one note fails on the first pass, is saved as a failed row, succeeds in the retry pass, and the failed row is overwritten.
- [ ] Run `python3 tests/verify_profile_collect_failure_backfill_backend.py`; expected result before implementation: failure because `append_profile_collect_failure` and retry overwrite behavior do not exist.
- [ ] Add `LarkWriter.build_profile_collect_failure_row`, `append_profile_collect_failure`, and `overwrite_profile_collect_record`.
- [ ] Add backend task counters: `failed_saved`, `retry_processed`, `retry_success`, `retry_failed`.
- [ ] In `_run_profile_collect_task`, after first pass, write failures into the profile sheet, then retry those rows once and overwrite successful rows.
- [ ] Run the new test until it passes.
- [ ] Add the new test to `tests/run_release_quality.py`.

### Task 2: Popup Progress Copy

**Files:**
- Modify: `extension/popup.js`
- Modify: `extension/background.js`

- [ ] Add phase label `retry_failed_rows` as `第 6 步：补采失败笔记`.
- [ ] Include retry counters in `backendTaskToProfileState` and `normalizeBackendTask`.
- [ ] Show running copy: `正在补采失败笔记：已处理 X/Y，补采成功 A，仍失败 B`.
- [ ] Show final copy: `失败已落表 N 条，补采成功 A 条，仍失败 B 条`.

### Task 3: Version, Packaging, Deployment

**Files:**
- Modify: `extension/manifest.json`
- Modify: `server/app.py`
- Modify: `CHANGELOG.md`

- [ ] Bump version to `4.7.3`.
- [ ] Run `python3 tests/run_release_quality.py`; expected all PASS.
- [ ] Deploy `server/app.py` and `server/lark_writer.py` to `/opt/xhs-collect`, restart `xhs-collect-api`, and verify `/api/health` returns `4.7.3`.
- [ ] Build clean `小红书一键收录-v4.7.3.zip`, verify manifest version and no sensitive/cache files.
- [ ] Copy the zip to the parent tool folder and sync `小红书一键收录-Atlas当前版/extension`.
- [ ] Insert online changelog entry for `4.7.3`.
- [ ] Commit and push to GitHub.
