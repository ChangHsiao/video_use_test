# 字幕高度依畫面比例決定：實作計畫
對應規格：specs/2026-10-09-subtitle-margin-by-aspect.md

## 步驟（給我看）
1. 先寫測試：直式維持原高度、橫式放低、`--sub-margin` 覆蓋、超出範圍報錯；執行後應該失敗
2. 改程式：依畫面寬高決定字幕高度，加上 `--sub-margin`
3. 改 SKILL.md：寫清楚直式／橫式的高度和新參數
4. 驗證：全部測試通過；新舊程式比對三份素材；B 段重新算繪、截圖看位置

## 細節（給 Agent）
### 步驟 1：`tests/test_render_sub_margin.py`
- `sub_margin_v(1080, 1920)` → 90；`sub_margin_v(1920, 1080)` → 23；方形 1080×1080 → 23；`None`（量不到）→ 90
- `sub_margin_v(1920, 1080, pct=5)` → 14；直式加 `pct` 也照 `pct`
- `sub_force_style("ja", margin_v=23)` 含 `MarginV=23`、不含 `MarginV=90`；不傳 `margin_v` 時和現在完全相同（三種語言）
- `--sub-margin 60` → argparse 報錯（`SystemExit`）

### 步驟 2：`helpers/render.py`
- 常數：`SUB_MARGIN_V_PORTRAIT = 90`（沿用官方）、`SUB_MARGIN_PCT_LANDSCAPE = 8`
- `sub_margin_v(width, height, pct=None) -> int`：`pct` 有值 → `round(288 * pct / 100)`；量不到 → 90；高 > 寬 → 90；其他 → `round(288 * 8 / 100)`
- `sub_force_style(sub_lang, font=None, margin_v=None)`：`margin_v` 有值時替換 `MarginV=...`
- `build_final_composite(..., margin_v=None)` 傳下去
- `main()`：有字幕要燒時量 `base_path` 寬高（`--build-subtitles` 時已量過就共用），算 `margin_v`，印出「subtitle margin: MarginV=N (x% from bottom)」
- `--sub-margin`：`type=float`，0～50 以外 `ap.error()`

### 步驟 3：`SKILL.md`
- Helpers 清單 `render.py` 補 `--sub-margin`
- `bold-overlay` 段落：`MarginV=35` 改成實際行為（直式 90、橫式約 8%），說明畫面在 render.py 之後才裁切時要傳 `--sub-margin`

### 驗證
- 執行指令：`uv run --with pytest python -m pytest -q`，預期原有 133 個 + 新增全部通過
- 新舊比對（輸出寫到 scratchpad）：對 podcast 16:9、B 段，比較 main 和新程式的 `force_style`：只有 `MarginV` 不同；另外用一個真正的直式畫面尺寸（1080×1920）確認和 main 相同
- 注意：podcast `vertical_skill_v2` 是 render.py 先算 16:9、之後才裁成 9:16，新程式會把它當橫式放低；這正是規格說的「之後才裁切要傳 `--sub-margin`」的情況（直式要傳 `--sub-margin 31` 才和現在一樣），驗證時確認傳了參數後 `MarginV=89～90`
- B 段：`ja_test/edit/verify_1a/` 重新算繪 `preview.mp4`（`--sub-lang ja`），截 2 張圖確認字幕在畫面下方、沒有貼到底邊
