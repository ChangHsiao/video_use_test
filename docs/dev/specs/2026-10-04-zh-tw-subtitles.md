# 繁體中文字幕
日期：2026-10-04　狀態：已同意

## 給我看的（白話，10 行以內）
- 要做什麼：讓 skill 除了英文字幕，也能燒繁體中文字幕；用一個開關切換，預設還是英文。
- 為什麼：目前的字幕是照英文設計的，中文會出現字中間多空格、兩個字一閃就換、字型沒有中文字（變方框）等問題。
- 怎麼做：render.py（渲染影片的程式）新增 `--sub-lang zh-tw` 開關，換掉斷句、字型等規則；SKILL.md（Claude 讀的說明書）教 Claude 依影片語言決定要不要加這個開關，並寫進剪輯策略讓你確認。
- 順便修：字幕檔改用 UTF-8（萬國碼，能正確存中文的編碼）寫入，避免 Windows 上出現亂碼。
- 不做什麼：簡繁轉換（OpenCC）、翻譯、程式自動判斷語言、其他語言。
- 怎樣算完成：分兩階段 ——
  1. 用自己編的中文逐字稿測試：字幕是繁體、沒有多餘空格、每句長度好讀、沒有方框；英文字幕的行為完全不變。不花轉錄額度。
  2. 用你準備的 1～3 分鐘中文影片實測（**你同意後才轉錄**），看 Scribe 輸出繁體還是簡體，再決定要不要另開規格加 OpenCC。

## 給 Agent 的（細節）

### 會影響的檔案
- `helpers/render.py`
- `SKILL.md`（Subtitles 段落、Helpers 清單中 `render.py` 那一行）
- 新增 `tests/test_render_captions_zh.py`（另開檔案，不改官方的 `test_render_captions.py`，減少合併 upstream 時的衝突）

### 不能改動的地方
- `--sub-lang` 預設為 `en`，此時 `master.srt` 的內容、`SUB_FORCE_STYLE`、`CHUNK_*` 常數、`chunk_words()` 的行為都與現在一致。現有測試必須全部通過。
- Hard Rules 不變：字幕最後疊（Rule 1）、輸出時間軸偏移（Rule 5）。
- 不修改 `transcribe.py`。

### 技術細節
1. **CLI**：`--sub-lang {en,zh-tw}`，預設 `en`。只影響 `--build-subtitles` 產生的 SRT 和燒字幕時的 `force_style`；EDL 指定現成 SRT 時只套用 `force_style`。
2. **語言設定集中管理**：每種語言一組設定（斷句函式、文字串接方式、是否轉大寫、force_style），`build_master_srt()` 和 `build_final_composite()` 依 `sub_lang` 取用，避免到處寫 `if`。
3. **zh-tw 斷句**（數值為初版，驗證時可調）：
   - 以「顯示寬度」而不是詞數計算長度：中文和全形標點算 2，英數字和空格算 1；每句上限 28（約 14 個中文字），超過就斷開。（2026-10-04 修訂：原寫「字數」，但中英夾雜時英文單字的每個字母不該跟一個中文字算一樣長。）
   - 遇到中文標點（`，。！？；：、`）或英文標點、或停頓 ≥ 0.3 秒時斷句。
   - 畫面停留時間太短（< 0.8 秒）時，在不超過字數上限的前提下併入下一個詞。
4. **文字串接**：中文詞與中文詞之間不加空格；相鄰兩個詞只要有一邊是英數字就補一個空格（例如「用 Claude Code 剪片」）。（2026-10-04 修訂：原寫「兩側都是英數字才補」，與例子不符，以例子為準。）
   - 合併規則：因停頓或標點斷開的 cue 若短於 0.8 秒，只有在「標點斷開、且下一個詞沒有停頓」時才併入下一句；停頓斷開的保持分開（與英文版「does | is」的處理一致）。
5. **標點與大小寫**：不轉大寫；去掉句尾的 `，。、；：`（字幕慣例），保留 `？！`。
6. **字型**：`FontName=Microsoft JhengHei`（微軟正黑體，`C:\Windows\Fonts\msjh.ttc`），其餘樣式沿用英文版（白字黑框、底部置中、`MarginV=90`），字級驗證時再調。必須用截圖確認字型真的有載入，不是 fallback 成方框或其他字型。
7. **編碼**：`build_master_srt()` 讀逐字稿、寫 SRT 時明確指定 `encoding="utf-8"`。英文模式也套用，內容不變。
8. **防呆警告**：`--build-subtitles` 且 `--sub-lang en` 時，若逐字稿的 `language_code` 是中文（`zh`/`cmn`/`yue` 開頭），或逐字稿文字中 CJK 字元佔多數，印出警告到 stderr，提示加上 `--sub-lang zh-tw`。只警告、不中斷。
9. **SKILL.md**：
   - Subtitles 段落新增一個 worked style `zh-tw`，說明上述規則和 `--sub-lang zh-tw`。
   - 寫明：Claude 依逐字稿的語言選擇字幕語言，在策略（流程第 4 步）寫出字幕語言和樣式，由使用者確認；使用者可隨時指定。
   - Helpers 清單中 `render.py` 那一行補上 `--sub-lang`。
10. **測試**：
    - 單元測試：用自編的中文 Scribe 格式逐字稿測斷句、串接（含中英夾雜）、標點處理、警告判斷。
    - 端到端：在 scratchpad 用 ffmpeg 產生測試影片（`testsrc` + 靜音或 sine 音軌），搭配自編逐字稿和 EDL，執行 `render.py --build-subtitles --sub-lang zh-tw --preview`，擷取畫面確認字幕顯示正常。

### 已知風險
- render.py 寫 concat 清單（`concat_list.write_text`）時也沒指定編碼，路徑含「長」時 ffmpeg 可能讀錯。不在本規格範圍；端到端測試若遇到，先停下來跟使用者討論是否一併修正。
- Windows 版 ffmpeg 的 libass 能否透過字型名稱找到微軟正黑體，需實測；找不到時可能要加 `fontsdir` 參數。
- `subtitles` filter 的 Windows 路徑跳脫（反斜線、中文字元）未曾在本機驗證過。

（2026-10-04 端到端測試後：第 1、3 條確實發生，已移入範圍，見下方修訂紀錄；第 2 條沒問題，ffmpeg 透過 DirectWrite 直接找到微軟正黑體。）

## 修訂紀錄

### 2026-10-04：端到端測試後擴大範圍（使用者同意在本分支修正）

| # | 發現的問題 | 原因 | 修法 |
|---|---|---|---|
| A | 路徑含「長」時，render.py 一開始就失敗（讀 EDL 出現 `UnicodeDecodeError: 'cp950'`），之後串接片段也失敗（ffmpeg `Invalid argument`） | `main()` 讀 EDL、`concat_segments()` 寫 `_concat.txt` 都沒指定編碼，Windows 預設 cp950（Big5）；ffmpeg 讀 concat 清單用 UTF-8，「長」被存成 Big5 的 `aa f8` | 兩處加 `encoding="utf-8"` |
| B | 燒字幕失敗，ffmpeg 回報 `Unable to parse "original_size" option value "Users長AppData..."` | Windows 路徑的反斜線被 ffmpeg filter 參數解析當成跳脫字元吃掉；英文字幕在 Windows 上同樣會失敗 | 路徑改用 `as_posix()`（正斜線），冒號照舊跳脫；已手動驗證可行 |
| D | A、B 修好後，音量標準化（loudnorm）失敗：`'NoneType' object has no attribute 'rfind'` | `measure_loudness()` 用 `text=True` 讀 ffmpeg 的 stderr，Python 以 cp950 解碼；stderr 含 UTF-8 的「長」路徑，解碼失敗後 `proc.stderr` 變成 `None` | 加 `encoding="utf-8", errors="replace"`（其他 `text=True` 的呼叫都是 ffprobe `-v error`，輸出不含路徑，不受影響） |
| C | 「怎麼用 Claude Code 剪輯影片。」被切成「…剪輯」＋「影片」，後者只停留 0.53 秒 | 寬度計算包含句尾「。」（寬度 29 > 28），但「。」最後會被去掉 | `chunk_words_zh()` 計算寬度時，先去掉句尾會被移除的標點再量 |

範圍擴大後，「不能改動的地方」仍然成立：英文模式的字幕內容、樣式、斷句不變（B 只改變路徑寫法，不影響字幕內容）。
