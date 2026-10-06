# 中文字幕：依詞斷句、轉成台灣繁體
日期：2026-10-05　狀態：已同意

## 給我看的（白話，10 行以內）
- 要做什麼：中文字幕只在「詞與詞之間」斷開，不再切出「全 / 力」；句首不再出現「，」；字幕和逐字稿（`takes_packed.md`）都轉成台灣繁體和台灣用語。
- 為什麼：2026-10-05 用自己錄的影片實測，Scribe（ElevenLabs 的語音轉文字服務）輸出的是簡體，而且字幕有 3 處斷在不對的地方。
- 怎麼做：加兩個套件。jieba（中文斷詞，MIT 授權）找出詞的邊界；OpenCC（簡繁轉換，Apache 2.0 授權）用 `s2twp` 設定轉成台灣繁體，例如「软件 → 軟體」「视频 → 影片」。順序是先用簡體斷詞，再轉繁體，因為 jieba 的詞典以簡體為主。
- 不做什麼：修正轉錄錯字（例如「好秒」）、改變每句字幕的長度上限、改動英文字幕、修改 `transcribe.py` 和轉錄存下來的 JSON。
- 怎樣算完成：
  1. 用自編的逐字稿做單元測試：停頓在詞中間不切開、句首沒有標點、簡體轉成台灣繁體；原本的測試全部通過。
  2. 用今天的測試影片重新產生字幕（不再轉錄、不花額度）：字幕是繁體，沒有「全 / 力」「伤 / 得」和句首「，」；`takes_packed.md` 是繁體，字與字之間沒有空格。

## 給 Agent 的（細節）

### 會影響的檔案
- `pyproject.toml`、`uv.lock`：用 `uv add jieba opencc` 加入**主要依賴**（`dependencies`，不是 optional）
- 新增 `helpers/zh_text.py`：放中文文字處理（斷詞、簡繁轉換、`display_width`、`join_zh` 等），`render.py` 和 `pack_transcripts.py` 共用
- `helpers/render.py`：`chunk_words_zh()`、`_format_cue_zh()`
- `helpers/pack_transcripts.py`：中文逐字稿的串接和轉換
- `SKILL.md`：Subtitles 的 `zh-tw` 段落、Helpers 清單中 `pack_transcripts.py` 那一行
- `tests/test_render_captions_zh.py`：新增測試案例

### 不能改動的地方
- `--sub-lang en`（預設）的行為完全不變，英文模式**不載入** jieba / OpenCC（只在需要時才 import）。
- 轉錄存下來的 JSON 不修改（Hard Rule 9：快取不可變）。轉換只發生在產生 SRT 和 md 的時候。
- Hard Rules 不變：字幕最後疊（Rule 1）、輸出時間軸偏移（Rule 5）。cue 的開始、結束時間仍然取自 Scribe 的逐字時間。
- `ZH_CHUNK_MAX_WIDTH = 28`、`ZH_CHUNK_MIN_S`、`CHUNK_PAUSE_S` 數值不變（使用者已確認直式畫面上折成兩行可以接受）。
- `render.py` 從 `zh_text.py` 重新 import 搬過去的函式，現有測試的 `from render import ...` 不用改。

### 技術細節
1. **詞邊界**（`zh_text.word_boundaries(tokens) -> set[int]`）：
   - 把 Scribe 的 token 文字直接接起來（不加空格），用 `jieba.lcut()` 斷詞，再把每個詞的字元位置對回 token。回傳「可以在第 i 個 token 之後斷開」的索引集合。
   - Scribe 的中文 token 通常一個字一個；如果某個 token 本身是多字詞，它內部本來就不會被切開，對應時以 token 為單位。
   - 一次處理整個 EDL range 的 token，不要一句一句處理（jieba 需要上下文）。
2. **`chunk_words_zh()` 的新規則**：
   - **停頓**：停頓 ≥ `CHUNK_PAUSE_S` 但位置在詞中間時，**不斷開**（使用者選擇以詞為優先）。
   - **寬度上限**：加入下一個 token 會超過 28 時，退回到目前 cue 裡最後一個詞邊界斷開，把不完整的詞移到下一句。如果目前 cue 裡沒有任何詞邊界（單一個詞就超過上限，極少見），才在 token 之間硬切。
   - **標點**：標點 token 一律跟著前一句，不會成為一句的開頭。如果標點前面剛好因為停頓斷開，就把標點併回前一句（之後句尾的 `，。、；：` 照舊被去掉）。
   - 原本的「標點 + 停留滿 0.8 秒才斷句」規則不變。
3. **簡繁轉換**（`zh_text.to_traditional(text) -> str`）：
   - `opencc.OpenCC("s2twp")`，模組層級只建立一次。
   - `_format_cue_zh()` 在 `join_zh()`、去掉句尾標點**之後**才轉換，所以寬度計算、斷詞都用簡體原文。
   - 已經是繁體的文字經過 `s2twp` 不變（已實測「原子習慣改變了我的人生」）。
   - `s2twp` 的詞彙轉換可能改變字數（例如某些用語），寬度以轉換前計算，誤差可接受，不另外處理。
4. **jieba 的雜訊**：
   - jieba 0.42.1 在 Python 3.12 import 時會印出 3 個 `SyntaxWarning`，以及「Building prefix dict…」等載入訊息到 stderr。import 時用 `warnings.catch_warnings()` 隱藏 `SyntaxWarning`，並用 `jieba.setLogLevel(logging.WARNING)` 關掉載入訊息。
   - 第一次斷詞要載入詞典，約 0.6 秒，可接受。
5. **`pack_transcripts.py`**：
   - 用 `looks_chinese()`（從 `render.py` 搬到 `zh_text.py`）判斷每個逐字稿是不是中文。是的話，片語文字改用 `join_zh()` 串接（字與字之間不加空格），再用 `to_traditional()` 轉換；不是的話維持原本的空格串接。
   - 自動判斷，不新增 CLI 參數。原因：md 只是給 AI 和人閱讀的檔案，不是成品，自動判斷錯了也不會影響影片。這跟字幕語言由 Claude 決定（見 `decisions.md` 2026-10-04）不同，字幕是成品的一部分。
   - 時間範圍、分段規則（停頓 ≥ 0.5 秒、換說話者）不變。
6. **SKILL.md**：
   - `zh-tw` 段落：拿掉「`zh-tw` does not convert Simplified to Traditional」那段，改成說明會依詞斷句、用 OpenCC `s2twp` 轉成台灣繁體。
   - Helpers 清單中 `pack_transcripts.py` 那一行：註明中文逐字稿會轉成繁體、不加空格。
7. **測試**（`tests/test_render_captions_zh.py`，用自編的簡體逐字稿，不呼叫 Scribe）：
   - 「某个同学全」和「力挥棒之后」之間有 0.34 秒停頓 → 不切開。
   - 一句寬度到上限時剛好在詞中間（例如「…自己伤得有多重」）→ 退到詞邊界斷開。
   - 停頓後接「，」→ 逗號併回前一句，下一句開頭沒有標點。
   - `to_traditional()`：「软件」→「軟體」、「视频」→「影片」，繁體輸入不變。
   - `pack_transcripts`：中文逐字稿輸出繁體、沒有空格；英文逐字稿輸出不變。
   - 英文模式不 import jieba / opencc（檢查 `sys.modules`）。
8. **實際影片驗證**：用 `my_video/edit/` 已經快取的逐字稿和 EDL，執行 `render.py --build-subtitles --sub-lang zh-tw --preview --fps 30`，檢查 `master.srt` 和截圖；重新執行 `pack_transcripts.py`，檢查 md。不重新轉錄。

### 已知風險
- **jieba 已停止維護**：最後一版 0.42.1 發布於 2020-01-20。目前在 Python 3.12 上可以執行，只有 `SyntaxWarning`。未來的 Python 版本如果把無效跳脫字元改成錯誤，jieba 會無法 import。考慮過的替代方案：`rjieba`（Rust 實作）、`pkuseg`（較重、需要下載模型）。
- **jieba 安裝需要建置**：PyPI 上只有原始碼套件（sdist），`uv` 第一次安裝時要先建置。今天實測時第一次安裝卡住超過 5 分鐘，重試後 4 秒完成，原因不明，安裝時要留意。
- **斷詞錯誤**：jieba 也會斷錯（實測把「有多重」斷成「有 / 多重」），只會讓斷句位置不理想，不會切在字中間。
- **`looks_chinese()` 搬家**：`render.py` 原本用它發出「中文逐字稿用了英文規則」的警告，搬到 `zh_text.py` 後要確認警告仍然正常。

## 修訂紀錄
規格同意之後才發現要改的地方記在這裡。內文直接改成新內容，
並在改過的地方加上「（YYYY-MM-DD 修訂，見修訂紀錄）」。
