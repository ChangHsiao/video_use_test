# 繁體中文字幕：實作計畫
對應規格：specs/2026-10-04-zh-tw-subtitles.md

## 步驟（給我看）
1. 你開一個新分支 `feat/zh-tw-subtitles`（我給指令）。
2. 先寫中文字幕的測試，這時跑會失敗，因為功能還沒做（先定義「對」長什麼樣子）。
3. 修 render.py 的字幕檔編碼，並整理出「每種語言一組設定」的結構；英文行為不變，官方原本的測試要全部通過。
4. 加上繁中的斷句、串接、字型規則和 `--sub-lang` 開關，讓第 2 步的測試通過。
5. 加上防呆警告：中文影片卻用英文模式時提醒。
6. 用 ffmpeg 做一支假影片加自編逐字稿，實際渲染一次，截圖檢查字幕。
7. 改 SKILL.md，教 Claude 什麼時候用這個開關。
8. 你看過 diff 後，我給 commit 指令。
9. 第二階段（另外進行）：你放 1～3 分鐘中文影片，同意後轉錄、渲染，決定要不要加 OpenCC。

每一步做完我會停下來說明改了什麼，第 3～7 步每步都會讓你看 diff。

## 細節（給 Agent）

### 步驟 1：開分支
- 在 `.claude/skills/video-use/` 執行 `git switch -c feat/zh-tw-subtitles`（由使用者執行）。
- 確認：`git branch --show-current`。

### 步驟 2：測試先行
- 新增 `tests/test_render_captions_zh.py`，沿用 `test_render_captions.py` 的 importlib 載入方式和 `w()` 輔助函式。
- 測資：自編中文 Scribe 格式逐字稿（逐字或逐詞的 `type: "word"`，含 `type: "spacing"` 項目），包含：一般句子、中文標點、≥ 0.3 秒停頓、超過 14 字的長句、中英夾雜（如「用 Claude Code 剪片」）、極短的詞。
- 測試項目：
  - 斷句：遇標點／停頓斷開；長句不超過字數上限；過短的 cue 會合併。
  - 串接：中文之間無空格；英數字之間保留一個空格。
  - 標點：去掉句尾 `，。、；：`，保留 `？！`；不轉大寫。
  - `build_master_srt(..., sub_lang="zh-tw")` 以 UTF-8 寫出、內容正確（用 tempdir）。
  - 警告判斷函式：`language_code` 為 `zh`/`cmn`/`yue` 開頭，或 CJK 佔多數時回傳 True；英文逐字稿回傳 False。
- 執行並確認失敗原因是「功能不存在」，不是測試本身寫錯。

### 步驟 3：編碼與語言設定結構
- 修改的檔案和位置：`helpers/render.py` 的 `build_master_srt()`（約 468–521 行）、`build_final_composite()`（約 633 行起）。
- 做法：
  - `tr_path.read_text(encoding="utf-8")`、`out_path.write_text(..., encoding="utf-8")`。
  - 新增 `SUB_LANGS` 字典，`"en"` 指向現有的 `chunk_words`、`" "` 串接、轉大寫、`SUB_FORCE_STYLE`。
  - `build_master_srt()` 和 `build_final_composite()` 新增 `sub_lang: str = "en"` 參數（預設值讓舊呼叫方式不變）。
  - 不動 `SUB_FORCE_STYLE`、`CHUNK_*`、`chunk_words()`。
- 驗證：既有測試全部通過。

### 步驟 4：zh-tw 規則與 CLI
- 新增 `ZH_CHUNK_MAX_WIDTH = 28`、`ZH_CHUNK_MIN_S = 0.8`、`ZH_PUNCT_BREAK`、`display_width()`、`chunk_words_zh()`、`join_zh()`、`SUB_FORCE_STYLE_ZH`（`FontName=Microsoft JhengHei`，其餘同英文版）。
- `SUB_LANGS["zh-tw"]` 指向上述函式與樣式，不轉大寫。
- `main()` 新增 `--sub-lang {en,zh-tw}`，預設 `en`，傳給 `build_master_srt()` 和 `build_final_composite()`。
- 驗證：步驟 2 的斷句、串接、標點、SRT 測試通過。

### 步驟 5：防呆警告
- 新增 `looks_chinese(transcript) -> bool`。
- `build_master_srt()` 在 `sub_lang == "en"` 且 `looks_chinese()` 為 True 時，印警告到 stderr（每次執行只印一次），不中斷。
- 驗證：步驟 2 的警告判斷測試通過；全部測試通過。

### 步驟 6：端到端
- 在 scratchpad 建立 `e2e/`：
  - `ffmpeg -f lavfi -i testsrc=size=1920x1080:rate=30 -f lavfi -i sine=frequency=440 -t 10 ... src.mp4`
  - `edit/transcripts/src.json`（自編中文逐字稿）、`edit/edl.json`（兩段 range，驗證時間偏移）。
- 執行：`uv run --project .claude/skills/video-use python .claude/skills/video-use/helpers/render.py <scratchpad>/e2e/edit/edl.json -o <scratchpad>/e2e/out.mp4 --build-subtitles --sub-lang zh-tw --preview`
- 檢查：
  - `master.srt` 用 UTF-8 開啟內容正確。
  - 用 ffmpeg 在幾個字幕時間點擷取畫面，以 Read 查看：中文正常顯示、無方框、字型是正黑體、位置和大小合理。
  - 同一份 EDL 用 `--sub-lang en` 跑一次，確認出現警告。
- 遇到 concat 清單路徑或字型載入問題 → 停下來，依規格「已知風險」跟使用者討論。
- 注意：scratchpad 路徑同樣含「長」，正好能測到路徑問題。

### 步驟 7：SKILL.md
- Helpers 清單 `render.py` 那一行補上 `--sub-lang en|zh-tw`。
- Subtitles 段落新增 worked style `zh-tw`（斷句、串接、標點、字型、`--sub-lang zh-tw`），並寫明：依逐字稿語言選擇字幕語言，在策略（第 4 步）寫出字幕語言和樣式，由使用者確認。
- 用英文撰寫，與 SKILL.md 其他內容一致。

### 步驟 8：提交
- 提供使用者指令：`git status`、`git diff`、`git add`（列出具體檔案，含 spec 和 plan）、`git commit`、`git push -u origin feat/zh-tw-subtitles`，並說明每一步的作用。
- 提醒把「開關由 Claude 指定，不在程式內自動判斷語言」記進 `decisions.md`（第 7 步回顧）。

### 驗證（總結）
- 執行指令：`uv run --project .claude/skills/video-use python -m unittest discover -s .claude/skills/video-use/tests -v`
- 預期結果：既有測試和新增的中文測試全部通過；端到端截圖中文字幕顯示正常；英文模式處理中文逐字稿時出現警告。
