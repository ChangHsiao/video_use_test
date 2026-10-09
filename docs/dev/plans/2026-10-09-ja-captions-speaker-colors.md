# 日文字幕與說話者顏色：實作計畫（1a）
對應規格：specs/2026-10-09-ja-captions-speaker-colors.md
1b（說話者顏色、修正）報告後另外補在這份計畫的後半。

## 步驟（給我看）
1. 先寫測試：日文判斷、日文逐字稿不加空格、日文字幕斷句、字型選項；執行後新的應該失敗
2. 語言判斷和斷詞：能分辨中文／日文，日文用 BudouX 找文節邊界
3. 逐字稿打包：日文不加空格、不轉繁體
4. 字幕：新增 `--sub-lang ja` 和 `--sub-font`；原本只給中文的規則（字數依畫面寬度、不重疊、拿掉太短的句子）改成中日文共用
5. 套件和說明：加入 BudouX；SKILL.md 補上 `ja` 樣式
6. 驗證：全部測試通過；用 B 段實際產生字幕、燒一版預覽，截圖檢查字型和斷句

## 細節（給 Agent）
### 步驟 1：測試（`tests/test_render_captions_zh.py` 新增，或另開 `test_render_captions_ja.py`）
- `transcript_lang()`：`zho` → `zh`、`jpn` → `ja`、有假名無標記 → `ja`、英文 → `None`
- `pack_transcripts`：日文 token 接起來沒有空格、`学` 不變成 `學`；英文、中文輸出不變（既有測試）
- `chunk_words_ja`：B 段式的單字 token，切點只落在 BudouX 文節邊界；超過寬度上限時切開；說話者換人斷句
- `_format_cue_ja`：無空格、不轉繁體、句尾 `、。` 去掉、`？！` 保留、句中標點換 En space
- `build_master_srt(sub_lang="ja")`：不重疊、拿掉不到 0.2 秒的句子（沿用中文規則）
- 日文逐字稿用 `en` 規則時有警告
- `--sub-font`：覆蓋 `force_style` 的 `FontName`；`ja` 預設字型依 `sys.platform`

### 步驟 2：`helpers/zh_text.py`
- 新增 `transcript_lang()`，`looks_chinese()` 改成 `transcript_lang(t) == "zh"`（既有測試照過）
- `word_boundaries(texts, lang="zh")`：`zh` 用 jieba（不變），`ja` 用 BudouX `load_default_japanese_parser().parse()`；第一次用到才載入（`functools.cache`）
- 檔名維持 `zh_text.py`（改名會動到 import，範圍外），在檔頭說明也處理日文

### 步驟 3：`helpers/pack_transcripts.py`
- `group_into_phrases(..., zh=...)` 改成 `lang=None|"zh"|"ja"`：`zh` → `to_traditional(join_zh())`，`ja` → `join_zh()`，`None` → 原本的英文接法
- `pack_one_file()` 用 `transcript_lang(data)`

### 步驟 4：`helpers/render.py`
- `chunk_words_zh(words, max_width, lang="zh")`：`word_boundaries` 帶 `lang`；`_rebalance`、`_merge_short_cues` 一路傳 `lang`。新增 `chunk_words_ja = partial(chunk_words_zh, lang="ja")`
- `_format_cue_ja()`：同 `_format_cue_zh()` 但不呼叫 `to_traditional()`
- `SUB_LANGS` 每個語言加 `"cjk": bool`；`ja` 項目：`chunk_words_ja`、`_format_cue_ja`、`SUB_FORCE_STYLE` 換成日文預設字型
- `build_master_srt()`、`main()` 裡的 `sub_lang == "zh-tw"` 改成 `SUB_LANGS[sub_lang]["cjk"]`（字寬上限、`--sub-max-chars`、不重疊、拿掉太短句子）
- 日文預設字型：`win32` → `Yu Gothic`、`darwin` → `Hiragino Sans`、其他 → `Noto Sans CJK JP`
- `--sub-font NAME`：把 `force_style` 的 `FontName=...` 換掉；任何語言都可用
- 警告：`en` 規則遇到 `transcript_lang()` 為 `zh` 或 `ja` 時，提示對應的 `--sub-lang`
- `--sub-lang` 的說明文字補上 `ja`

### 步驟 5
- `pyproject.toml` 加 `budoux>=0.9`，執行 `uv lock` 更新 `uv.lock`
- `SKILL.md`：Helpers 清單的 `render.py` 補 `ja` 和 `--sub-font`；字幕樣式加一段 `ja`（BudouX 文節、字型預設、不轉繁體、其餘同 `zh-tw`）；「Choosing the caption language」補日文

### 驗證
- 執行指令：`uv run --with pytest python -m pytest -q`
- 預期結果：原有 109 個 + 新增測試全部通過
- 真資料（不動 `ja_test/edit/` 的固定檔名）：在 `ja_test/edit/verify_1a/` 放一份暫時的 `edl.json`（整段 0–156.36 秒）和複製的逐字稿，執行 `render.py edl.json -o preview.mp4 --preview --build-subtitles --sub-lang ja`
  - 檢查 `master.srt`：沒有空格、沒有從文節中間斷開、每句不超過 14 字
  - 截 3 張有字幕的畫面：字型是日文字型、沒有方框、一行放得下
- 已知不在 1a 範圍：最後 11 秒說話者標反（1b）、「終章」被聽成「秋生」（第 2 階段詞彙表）

---

# 1b：說話者顏色和修正

## 步驟（給我看）
1. 先寫測試：EDL 設定說話者顏色後字幕有顏色、沒設定時完全不變；說話者修正範圍內的字改成指定的人；英文也能依說話者上色
2. 改程式：讀 EDL 的 `speakers`（名字、顏色）和 `speaker_fixes`（修正範圍），產生字幕時套用
3. 改 SKILL.md：說明兩個新欄位，加上「上色前先檢查說話者標記」的步驟
4. 驗證：B 段設定兩位主持人的顏色、修正最後 11 秒，重新算繪並截圖確認

## 細節（給 Agent）
### 步驟 1：`tests/test_render_speakers.py`
- `speakers` 有設定：每句字幕包成 `<font color="#RRGGBB">…</font>`，顏色依該句第一個字的說話者；沒有對照到的說話者 → 不加標籤
- 沒有 `speakers`：`master.srt` 和現在逐字相同（en、zh-tw、ja 各一）
- `speaker_fixes`：範圍內（字的開始時間落在 `[start, end)`）的字改成指定說話者；只影響該 `source`；修正後斷句會跟著換人斷開
- 英文 + `speakers`：兩人的字不會出現在同一句
- 輸入檢查：顏色不是 `#RRGGBB` → 報錯並指出是哪個說話者

### 步驟 2：`helpers/render.py`
- `_apply_speaker_fixes(words, fixes)`：複製字典再改 `speaker_id`，不改到逐字稿原始資料
- `build_master_srt()`：每個 range 取字後先套 `speaker_fixes`（只取該 source 的）；有 `speakers` 時先依說話者切成連續段，每段各自 `chunk_fn`；格式化後依第一個字的說話者加 `<font color>`
- 「不重疊、太短拿掉」照舊作用在最後的句子上（標籤不影響時間）
- 顏色格式檢查放在 `build_master_srt()` 開頭，錯誤訊息寫出 source 和 speaker

### 步驟 3：`SKILL.md`
- EDL 範例或說明加上 `speakers`、`speaker_fixes`
- 字幕段落加一段：要用說話者顏色前，AI 先依內容檢查 Scribe 的說話者標記（叫對方名字、「我要上台」這類自述、問答的方向），列出可疑範圍給使用者聽過確認，確認後才寫進 `speaker_fixes`；名字和顏色也由使用者確認
- 說明顏色寫在 `master.srt` 裡（`<font color>`），校對時改標籤裡的文字即可

### 驗證
- `uv run --with pytest python -m pytest -q`：原有 142 個 + 新增全部通過
- 新舊比對（共用規則有改）：podcast 16:9、9:16、B 段在**沒有** `speakers` 時，`master.srt` 和 main 逐字相同（輸出到 scratchpad）
- B 段：`ja_test/edit/verify_1a/edl.json` 加上 `speakers`（speaker_0 田中美海、speaker_1 高橋李依，顏色待使用者確認）和最後 11 秒的 `speaker_fixes`（依使用者 10/9 聽過的結果），重新算繪 `preview.mp4`，截圖確認兩種顏色和修正後的段落
