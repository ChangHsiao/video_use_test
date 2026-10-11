# 翻譯與雙語字幕：實作計畫
對應規格：specs/2026-10-11-bilingual-translation.md

## 步驟（給我看）
1. 先寫測試：漏句、重複、順序錯會報錯；時間和顏色照草稿；雙語兩行的格式；草稿被改過會報錯；跨說話者、字太多會警告；日文被修正的地方會列進審稿清單。確認現在跑會失敗（工具還不存在）
2. 寫新工具 `helpers/bilingual_srt.py`，讓測試通過
3. 改 SKILL.md：工具說明、翻譯規則（補省略、意譯、標記猜測、套用詞彙表）
4. 實際跑 B 段：產生日文草稿 → AI 寫 `translation.json` → 工具產生雙語字幕和審稿清單 → 燒成預覽，我先看截圖檢查，再交給你看影片和審稿清單
5. 確認沒有動到既有功能：`render.py` 沒有修改、原有測試全過

## 細節（給 Agent）
### 步驟 1、2：`bilingual_srt.py` 和測試
- 修改的檔案和位置：新增 `helpers/bilingual_srt.py`、`tests/test_bilingual_srt.py`（沿用 `test_render_speakers.py` 的 `load_helper` 寫法）
- 做法（繁中註解，見 memory「自己新增的檔案用繁中註解」）：
  - `parse_srt(text) -> list[Cue]`：`Cue(index, start, end, text, colour)`；`colour` 取最外層 `<font color="#RRGGBB">`，`text` 去掉標籤
  - `load_translation(path)`、`check_draft_hash(tr, draft_bytes) -> bool`：沒有 `draft_sha256` 就寫入並存回檔案（保留其他欄位、`ensure_ascii=False`、縮排 2）；不同 → `sys.exit` 說明「草稿和寫翻譯時不同，句子編號已經對不上，重新寫 translation.json 或還原草稿（看 master.srt.bak-*）」
  - `validate_groups(cues, groups, drop, n) -> list[str]`（錯誤清單）：`from ≤ to`、在 1..n 內、依序不重疊、每句恰好出現一次（群組或 drop）、`src`／`tr` 非空；一次列出全部錯誤
  - `build(draft_cues, tr, max_chars, src_scale, src_font) -> (bilingual, src_only, tr_only, warnings)`：時間 = `cues[from].start`～`cues[to].end`；顏色 = `cues[from].colour`；組內有不同顏色 → 警告；`render._cue_width` 不適用（它吃 word dict），自寫 `display_width(s)`（CJK／全形 = 2，其他 = 1，同 render 的定義；先看 `zh_text.py` 有沒有現成的）；`tr` > `2*max_chars` 或 `src` > `2*max_chars/src_scale` → 警告
  - 雙語行：`<font color="C">{tr}\n<font face="{src_font}" size="{round(18*src_scale)}">{src}</font></font>`；沒有顏色就只包 `<font face size>`。18 取自 `render.SUB_FORCE_STYLE` 的 `FontSize`（用 regex 讀，不寫死）
  - 字型：`src_font` 預設 = `render.SUB_LANGS[source_lang]["force_style"]` 的 `FontName`；`--src-font` 覆蓋
  - 字寬上限：`--max-chars`；沒給時讀草稿旁的 `edl.json` 第一個 source，`render.probe_display_dimensions` + `render.zh_max_width`；都拿不到就用 14
  - 審稿清單 `translation_review.md`：① `check` 的句子（表格：組、時間、說話者顏色、原文、譯文、原因）② 原文修正：草稿 `from..to` 文字串接，和 `src` 都去掉空白、En space、標點後比較，不同就列「草稿 → 修正」③ 警告
  - 輸出：`master_bilingual.srt`、`master_<source_lang>.srt`、`master_<target_lang>.srt`（單語言也帶顏色）、`translation_review.md`，都寫在 `translation.json` 同一個資料夾；寫入前若已存在且內容不同，沿用 `render.replace_with_backup` 備份
  - CLI：`bilingual_srt.py <translation.json> [--max-chars N] [--src-scale 0.75] [--src-font NAME]`；結尾印出產生的檔案、警告數、`check` 數
- 測試（假 SRT 字串，`tempfile`）：
  - 驗證：漏號、重複、交錯、超出範圍、`drop` 正確排除、空白譯文 → 各一個
  - 時間取頭尾、顏色取第一句、兩行格式（含沒有顏色的情況）
  - 雜湊：第一次寫入、相同通過、不同報錯
  - 警告：跨顏色、`tr` 超長、`src` 超長；邊界剛好等於上限不警告
  - 原文修正：只合併不改字 → 不列；秋生 → 終章 → 列出

### 步驟 3：SKILL.md
- Helpers 清單（`export_xml.py` 後）加一條 `bilingual_srt.py`
- Subtitles 段落「Choosing the caption language」後加「Translation and bilingual captions」：流程（cut locked → `--subtitles-only` 草稿 → 讀詞彙表 → 寫 `translation.json` → 工具 → 交審稿清單 → EDL `subtitles: master_bilingual.srt` → `render.py --sub-lang <target>` 不加 `--build-subtitles`）和規格列的翻譯規則；`translation.json` 範例

### 步驟 4：B 段實測
- 資料夾 `ja_test/edit/bilingual/`：從 `trial_zh/` 複製 `edl.json`（`subtitles` 改成 `master_bilingual.srt`）、`transcripts/`
- `render.py --subtitles-only --sub-lang ja` → 草稿；讀 `glossaries/fgo.md`、草稿、`takes_packed.md` 寫 `translation.json`
- 工具 → `render.py edl.json -o preview_bilingual.mp4 --preview --sub-lang zh-tw`
- 自查：抽 6～8 個時間點截圖（含最長的句子、說話者交接、結尾換人處），檢查兩行不重疊、不折行、顏色正確；看審稿清單

### 驗證
- 執行指令：
  - `uv run --project .claude/skills/video-use python -m unittest discover -s .claude/skills/video-use/tests`
  - `git diff main --stat`：`helpers/render.py` 不在清單裡
  - 步驟 4 的實測
- 預期結果：測試全過；render.py 沒變；預覽符合規格「怎樣算完成」（中文沒有單獨的連接詞或單字句、詞彙表譯名都套用、審稿清單完整），最後由使用者看影片確認
