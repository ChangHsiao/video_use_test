# 防止校對過的字幕被蓋掉：實作計畫
對應規格：specs/2026-10-10-protect-proofread-subtitles.md

## 步驟（給我看）
1. 先寫測試：「內容不同會留備份」「內容相同不留備份」「原本沒有檔案就直接寫」，確認現在的程式會失敗
2. 加上「先備份再覆蓋」，讓測試通過
3. 加上 `--subtitles-only`（只產生字幕）和「EDL 已指定字幕」的警告
4. 改 SKILL.md：新參數、校對後改用 EDL `subtitles`、剪輯確定後才校對翻譯
5. 驗證：在暫存資料夾複製 `ja_test` 實際跑一次，再和 main 比對 `ja_test`、`podcast_test` 產生的字幕內容

## 細節（給 Agent）
### 步驟 1、2：備份
- 修改的檔案和位置：`helpers/render.py` 新增 `replace_with_backup(new_path, out_path) -> Path | None`（放在 `build_master_srt` 後面）；`main()` 的字幕段落改成 `build_master_srt(... out_path=master.srt.tmp)` 再呼叫它。新測試檔 `tests/test_render_subtitles_backup.py`
- 做法：比對位元組。相同 → 刪掉暫存檔、印 `master.srt unchanged`、回傳 None；不同 → 舊檔改名 `master.srt.bak-YYYYMMDD-HHMMSS`（同一秒已存在就加 `-2`），暫存檔 `replace` 成 `master.srt`，印出備份路徑和「proofread captions: point the EDL `subtitles` at the file instead of passing --build-subtitles」，回傳備份路徑；原本不存在 → 直接改名。時間用參數傳入方便測試
- 測試（`tempfile.TemporaryDirectory`）：三種情況各一個，加「同一秒兩次備份不互相覆蓋」

### 步驟 3：`--subtitles-only` 和警告
- 修改的檔案和位置：`helpers/render.py` 的 `main()`、參數定義；把「算字寬上限 + 產生 + 備份」抽成 `build_subtitles_step(edl, edit_dir, args, dims)`，兩種模式共用
- 做法：
  - `-o` 改成 `required=False`，沒給 `-o` 又不是 `--subtitles-only` 時 `ap.error`
  - `--subtitles-only` 和 `--no-subtitles` 同時給 → `ap.error`
  - `--subtitles-only`：尺寸用新函式 `probe_display_dimensions(video)`（`probe_dimensions` + 旋轉 90／270 度時交換寬高，邏輯從 `is_portrait_source` 抽出共用），素材取 EDL 第一個 range 的 source；產生後直接 return，不切片段
  - `--build-subtitles` 且 EDL 有 `subtitles` → 印警告
- 測試：`probe_display_dimensions` 的旋轉交換（mock `subprocess.run`，沿用 `test_render_orientation.py` 的寫法）

### 步驟 4：SKILL.md
- 第 78 行 render.py 說明加 `--subtitles-only`（builds only `master.srt`, no render — use it to get a draft to proofread or translate）；existing `master.srt` is backed up when the new one differs
- 第 316 行 `subtitles` 說明後加：once captions are proofread or translated, point `subtitles` at that file and render without `--build-subtitles`. Proofread/translate only after the cut is locked — the SRT is on output-timeline times, so any cut change means rebuilding and redoing the edits; tell the user before changing the cut

### 驗證
- 執行指令：
  - `uv run --project .claude/skills/video-use python -m unittest discover -s .claude/skills/video-use/tests`（全部通過）
  - 複製 `ja_test/edit/verify_1a/`（edl.json、transcripts）到 scratchpad：① `--subtitles-only --sub-lang ja` → 產生 `master.srt`，沒有任何 mp4、幾秒內完成 ② 再跑一次 → 印 unchanged、沒有備份 ③ 手動改一句再跑 → 出現 `.bak-*`，內容是改過的版本 ④ 和 `verify_1a/master.srt`（完整算繪產生的）比對相同
  - 不能改動的地方：用 `git worktree` 或 `git show main:helpers/render.py` 取得舊版，對 `ja_test`（ja）、`podcast_test`（zh-tw，含 9:16 `--sub-max-chars 10`）產生字幕到暫存資料夾，和新版逐位元組比對。舊版不用整支算繪：暫存腳本載入 main 的 render.py，用「之前算繪出的影片尺寸」（`base_preview.mp4`）算字寬上限後直接呼叫 `build_master_srt`；新版用 `--subtitles-only`（同時驗證「改看原始素材尺寸」算出的上限一樣）
- 預期結果：測試全過；四個情況符合；新舊字幕完全相同
