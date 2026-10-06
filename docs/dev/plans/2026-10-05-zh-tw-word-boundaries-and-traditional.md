# 中文字幕：依詞斷句、轉成台灣繁體：實作計畫
對應規格：specs/2026-10-05-zh-tw-word-boundaries-and-traditional.md

## 步驟（給我看）
1. 你先把昨天的 `feat/zh-tw-subtitles` 合併進 `main`，再從 `main` 開新分支 `feat/zh-tw-word-boundaries`（我給指令）。
2. 我用 `uv add` 加入 jieba 和 OpenCC，確認在 skill 的環境裡能正常載入。
3. 先寫新的測試。這時執行會失敗，因為功能還沒做。
4. 把中文文字處理的函式從 `render.py` 搬到新檔案 `zh_text.py`，`render.py` 和 `pack_transcripts.py` 都能使用。這一步只是搬家，所有舊測試都要通過。
5. 加入斷詞和簡繁轉換，修改字幕的斷句規則，讓第 3 步的字幕測試通過。
6. 讓 `takes_packed.md` 遇到中文時轉成繁體、字與字之間不加空格。
7. 更新 SKILL.md 的說明。
8. 用今天的影片重新產生字幕和 md，截圖檢查（不重新轉錄）。
9. 你看過 diff 後，我給 commit 指令。

第 2～8 步每做完一步，我會停下來說明改了什麼，並讓你看 diff。

## 細節（給 Agent）

### 步驟 1：合併昨天的分支、開新分支（由使用者執行）
- 在 `.claude/skills/video-use/` 執行：
  - `git switch main`
  - `git merge --ff-only feat/zh-tw-subtitles`（main 沒有新的 commit，應該可以 fast-forward；失敗就停下來討論）
  - `git push origin main`
  - `git switch -c feat/zh-tw-word-boundaries`
- 確認：`git branch --show-current`、`git log --oneline -3`。

### 步驟 2：加入依賴
- 執行：`uv add --project .claude/skills/video-use jieba opencc`
- 預期：`pyproject.toml` 的 `dependencies` 多了 `jieba>=0.42.1`、`opencc>=1.4.2`；`uv.lock` 更新。
- jieba 只有 sdist，第一次要建置。今天實測時曾經卡住超過 5 分鐘：用 `run_in_background` 執行，超過 5 分鐘沒有進展就停掉，改用 `-v` 重試，並回報使用者。
- 驗證：`uv run --project .claude/skills/video-use python -c "import jieba, opencc; print(opencc.OpenCC('s2twp').convert('软件'))"` 印出「軟體」。

### 步驟 3：測試先行
- 修改的檔案：`tests/test_render_captions_zh.py`（只新增，不改既有案例）。
- 新增的測資：模擬 Scribe 實際的格式，**一個中文字一個 token、標點獨立成一個 token**（今天的 JSON 就是這樣，例如 `'象'`、`'。'`），以簡體撰寫。
- 新增的測試：
  - 停頓在詞中間：「某个同学全」+ 0.34 秒停頓 +「力挥棒之后」→ 「全力」在同一句。
  - 寬度上限落在詞中間：「惊吓与困惑让我搞不清楚自己伤得有多重」→ 不在「伤 / 得」之間斷開，每句寬度 ≤ 28。
  - 停頓後的標點：「…骨折」+ 停頓 +「，」+「两个眼窝也碎了」→ 第二句開頭不是「，」。
  - `zh_text.to_traditional()`：「软件」→「軟體」、「视频」→「影片」、「原子習慣改變了我的人生」不變。
  - `zh_text.word_boundaries()`：多字 token 內部不產生邊界；中英夾雜（「用 Claude Code 剪辑」）對應正確。
  - `build_master_srt(..., sub_lang="zh-tw")` 的輸出是繁體。
  - `pack_transcripts`：中文逐字稿輸出繁體、沒有空格；英文逐字稿輸出和現在完全一樣。
  - 英文模式不載入 jieba / opencc：用子行程執行 `build_master_srt(..., sub_lang="en")`，檢查 `sys.modules`（避免被同一個測試行程裡其他測試已經載入的狀態干擾）。
- 執行並確認失敗原因是「功能不存在」（例如 `ModuleNotFoundError: zh_text`），不是測試寫錯。

### 步驟 4：搬到 `zh_text.py`（行為不變）
- 新增 `helpers/zh_text.py`，從 `render.py` 搬入：`display_width`、`_is_latin`、`_is_cjk_punct`、`join_zh`、`looks_chinese`，以及 `ZH_PUNCT_BREAK`、`ZH_TRAILING_STRIP`。
- `render.py`：
  - 檔案開頭把 `Path(__file__).parent` 加進 `sys.path`，再 `from zh_text import ...`。原因：測試用 `importlib` 依路徑載入 `render.py`，這時 helpers 資料夾不在 `sys.path` 上（`grade` 的 import 也有同樣問題，但它有 fallback，所以一直沒被發現；這次不改 `grade` 的部分）。
  - 搬過去的名稱在 `render.py` 仍然可以用 `render.join_zh` 存取，既有測試不用改。
  - `import unicodedata` 若已沒有其他地方使用就移除。
- 驗證：全部既有測試通過（`unittest discover`），新測試仍然失敗。

### 步驟 5：斷詞與簡繁轉換
- `zh_text.py` 新增：
  - `_jieba()`、`_opencc()`：第一次呼叫時才 import，並快取。import jieba 時用 `warnings.catch_warnings()` + `simplefilter("ignore", SyntaxWarning)`，之後 `jieba.setLogLevel(logging.WARNING)`。
  - `word_boundaries(texts: list[str]) -> set[int]`：把 token 文字接起來，`jieba.lcut()` 斷詞，累計每個詞的結束位置；token i 的結束位置剛好是某個詞的結束位置時，i 就是可斷開的位置。最後一個 token 一定可斷開。
  - `to_traditional(text: str) -> str`：`OpenCC("s2twp").convert(text)`。
- `render.py` 的 `chunk_words_zh()`：
  - 開頭過濾空白 token 之後，呼叫 `word_boundaries()`。
  - 停頓斷句：多加條件「i 在邊界集合中」。
  - 寬度上限：超過時往回找 `current` 中最後一個可斷開的位置，切開後把剩下的 token 帶到新的 `current`；找不到邊界才照舊整句切開。
  - 標點：token 本身是標點（每個字元的 Unicode category 都是 `P*`）且 `current` 是空的時候，把它接到 `chunks[-1]` 的尾端，不開新句。
  - 「標點 + 停留 ≥ `ZH_CHUNK_MIN_S`」的斷句規則不變。
- `_format_cue_zh()`：`join_zh()` → 去掉句尾標點 → `to_traditional()`。
- 驗證：步驟 3 的字幕和 `zh_text` 測試通過；既有中文測試仍然通過。**既有測試的測資是繁體、多字 token，jieba 的斷詞可能改變它們的斷句結果；如果既有測試因此失敗，停下來回報，不要直接改測試的預期值。**

### 步驟 6：`pack_transcripts.py`
- `pack_one_file()`：`json_path.read_text()` 改成 `read_text(encoding="utf-8")`。（目前沒出錯，是因為 `transcribe.py` 用 `ensure_ascii=True` 存檔，內容全是 ASCII；這行的寫法本身在 Windows 上不安全。）
- 用 `looks_chinese(data)` 判斷，把結果傳給 `group_into_phrases()`（新增參數 `zh: bool = False`）。
- `flush()` 中：`zh` 為 True 時用 `join_zh(text_parts)` 再 `to_traditional()`；False 時維持 `" ".join(...)` 和後面的標點修正，一個字都不改。
- `pack_transcripts.py` 開頭同樣把自己的資料夾加進 `sys.path`，再 `from zh_text import ...`。
- 驗證：步驟 3 的 `pack_transcripts` 測試通過。

### 步驟 7：SKILL.md（用英文撰寫）
- Subtitles 的 `zh-tw` 段落：
  - 刪除「`zh-tw` does not convert Simplified to Traditional — if Scribe returns Simplified characters, the captions are Simplified; tell the user.」
  - 補充：cue 只在 jieba 判斷的詞邊界斷開（詞中間的停頓不會切開），標點跟著前一句，文字用 OpenCC `s2twp` 轉成台灣繁體和用語。
- Helpers 清單中 `pack_transcripts.py` 那一行：補上「Chinese transcripts are joined without spaces and converted to Traditional (Taiwan)」。

### 步驟 8：實際影片驗證
- 把 `my_video/edit/master.srt` 備份成 `master.manual.srt`（保留今天手動修正的版本）。
- 執行：
  - `uv run --project .claude/skills/video-use python .claude/skills/video-use/helpers/pack_transcripts.py --edit-dir my_video/edit`
  - `uv run --project .claude/skills/video-use python .claude/skills/video-use/helpers/render.py my_video/edit/edl.json -o my_video/edit/preview.mp4 --preview --fps 30 --sub-lang zh-tw --build-subtitles`
- 檢查：
  - `takes_packed.md`：繁體、字與字之間沒有空格。
  - `master.srt`：繁體；沒有「全 / 力」「傷 / 得」；沒有以標點開頭的句子；每句寬度 ≤ 28。
  - 擷取 3～5 張畫面確認字幕顯示正常。
- 最後把今天的兩處手動修正（毫秒、顱部）套回新的 `master.srt`，不加 `--build-subtitles` 再算繪一次，留給使用者看。

### 步驟 9：提交
- 提供使用者指令：`git status`、`git diff`、`git add`（列出具體檔案，含 spec 和 plan）、`git commit -F <scratchpad 檔案>`、`git push -u origin feat/zh-tw-word-boundaries`，並說明每一步的作用；commit 訊息格式和學習階段依 `git-commit-guide.md`。
- 第 7 步回顧時提醒記進 `decisions.md`：
  - 採用 OpenCC `s2twp`（取代 2026-10-04「OpenCC 延後」的紀錄）
  - jieba 和 OpenCC 放在主要依賴
  - `pack_transcripts.py` 自動判斷中文，不加參數

### 驗證（總結）
- 執行指令：`uv run --project .claude/skills/video-use python -m unittest discover -s .claude/skills/video-use/tests -v`
- 預期結果：既有測試和新增測試全部通過；實際影片的 `master.srt`、`takes_packed.md` 符合步驟 8 的檢查項目。
