# v3.1 性能基线（实测）

> 时间：2026-05-22 凌晨
> 测试方法：`time curl -s` 实测
> 测试机：本地 Mac → 14.22.112.147:8866

## 修复前 vs 修复后对比

| API | 修复前 | 修复后（缓存命中）| 倍数 |
|---|---|---|---|
| GET /api/check（跨 8 sheet）| 3.435s | 99ms | **35x** |
| GET /api/dashboard | 4.060s | 77ms | **53x** |
| GET /api/failures | 3.125s | 76ms | **41x** |

## 修复方法

新增三个内存缓存（LarkWriter 实例属性）：
- `_notes_cache`：spreadsheet_token → {note_id: {sheet_id, sheet_title, row}}，TTL 30s
- `_dashboard_cache`：spreadsheet_token → {stats, all_records}，TTL 30s
- `_failures_cache`：spreadsheet_token → list[failure]，TTL 30s
- `_sheets_cache`：spreadsheet_token → list[sheet]，TTL 60s

写入操作（collect/retry/update/create_sheet/delete_sheet）会主动 `invalidate_cache()`。

## 实测原始数据

```
[2026-05-22 21:48] /api/check 跨 sheet 性能
  测试 1 - 已存在笔记: 3.435 total
  测试 2 - 不存在笔记: 3.269 total

[2026-05-22 21:51] 缓存修复后
  第一次 /api/check（冷启动，构建缓存）: 3.753 total
  第二次 /api/check（命中缓存）: 0.099 total
  第三次 /api/check（命中缓存）: 0.116 total

[2026-05-22 21:55] Dashboard 缓存验证
  第一次（冷启动）: 4.060 total
  第二次（缓存命中）: 0.077 total
  第三次（缓存命中）: 0.079 total

[2026-05-22 21:55] Failures 缓存验证
  冷: 3.125 total
  热: 0.076 total
```

## 用户感受

- 第一次打开 popup（冷启动同时调 whoami + sheets + check + dashboard）：约 4 秒
- 30 秒内连续操作：每次 < 200ms（流畅）
- 缓存 TTL 30 秒，过期后下次自动重建
