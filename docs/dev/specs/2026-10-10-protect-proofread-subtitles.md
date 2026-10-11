# 防止校對過的字幕被蓋掉
日期：2026-10-10　狀態：已完成

屬於「日文雙語字幕」第 2 階段的前置修正，全部階段見專案根目錄的 `工作地圖.md`。

## 給我看的（白話，10 行以內）
- 要做什麼：重新產生字幕時，不會把校對或翻譯過的 `master.srt` 蓋掉；也能只產生字幕、不算繪影片
- 為什麼：`render.py --build-subtitles` 每次都從逐字稿重新產生 `master.srt`，不會提示，手動改過的內容就沒了（10/5 發現）。第 2 階段 Claude 會翻譯、校正字幕，一定會碰到。另外翻譯要先拿到日文字幕草稿，現在只能等整支影片算繪完
- 怎麼做：① `master.srt` 已存在、內容又不同時，先另存備份再覆蓋，並印出提示 ② 新增 `--subtitles-only`：只產生 `master.srt`，幾秒內完成，不切片段、不算繪 ③ SKILL.md 寫明：字幕校對或翻譯過之後，在 EDL（剪輯清單 `edl.json`）的 `subtitles` 欄位指定檔案，不要再加 `--build-subtitles`；剪輯確定之後才校對、翻譯（權宜之計，見「技術細節」）
- 不做什麼：拒絕覆蓋（AI 會卡住，或學會加強制參數）；翻譯、詞彙表、兩條字幕同時燒
- 怎樣算完成：在 `ja_test` 的副本上，改過的 `master.srt` 重新產生後，備份檔內容和改過的一樣；內容沒變時不產生備份；`--subtitles-only` 不產生影片、幾秒內完成，字幕和完整算繪產生的一模一樣；原有測試全過

## 給 Agent 的（細節）
- 資料流：逐字稿 JSON + EDL → `render.py --build-subtitles`（或 `--subtitles-only`）→ `edit/master.srt` → Claude／使用者校對、翻譯（改的就是這個檔案，或另存新檔）→ EDL `subtitles` 指向校對過的檔案 → `render.py`（不加 `--build-subtitles`）燒進畫面。會失效的情況：校對後又加 `--build-subtitles`，這次的修改讓舊內容至少留在備份裡
- 會影響的檔案：`helpers/render.py`（`main()` 的字幕段落、新參數、備份函式）、`SKILL.md`（Helpers 的 render.py 說明、EDL `subtitles` 段落）、新測試檔 `tests/test_render_subtitles_backup.py`
- 不能改動的地方：
  - `master.srt` 的內容（斷句、時間、顏色）完全不變；只多了「寫之前先備份」
  - 沒有既有 `master.srt`、或內容相同時，`edit/` 裡的檔案和現在一樣（不多出備份檔）
  - 不加新參數時，算繪流程和輸出影片不變
  - 怎麼確認：`ja_test`、`podcast_test` 各用 main 和新程式 `--build-subtitles` 產生字幕到暫存資料夾比對，內容要相同
- 通用性檢查：備份檔名只用時間，不含個人資料；路徑用 `pathlib`，任何作業系統都能用；所有語言（`en`／`zh-tw`／`ja`）共用
- 技術細節：
  - **備份**：新函式 `write_srt_with_backup(out_path, build_fn)` 的概念 —— 先產生到同資料夾的暫存檔 `master.srt.tmp`，和既有 `master.srt` 比對位元組：相同 → 刪暫存檔，印「master.srt unchanged」；不同 → 既有檔改名成 `master.srt.bak-YYYYMMDD-HHMMSS`，暫存檔改名成 `master.srt`，印出備份路徑並提醒「校對過的字幕請用 EDL `subtitles` 指定」；原本不存在 → 直接改名
  - **`--subtitles-only`**：隱含 `--build-subtitles`；跳過切片段、合併、疊圖、音量標準化；`-o` 變成選填（只在這個模式下）。字寬上限（`zh-tw`／`ja`）需要輸出畫面尺寸：改用 EDL 第一個 range 的原始素材尺寸（含旋轉資訊，沿用 `is_portrait_source` 的旋轉判斷），因為上限只看寬高比；`--sub-max-chars` 照常可覆蓋。和 `--no-subtitles` 同時給時報錯
  - **EDL 有 `subtitles` 又加 `--build-subtitles`**：印出警告「EDL 指定的字幕會被忽略，改用重新產生的 master.srt」（行為不變，只多警告）
  - SKILL.md 的 render.py 說明加上 `--subtitles-only` 和「校對後改用 EDL `subtitles`」一句；EDL 範例下方 `subtitles` 的說明補一句同樣的規則
  - **權宜之計**：SKILL.md 再加「剪輯確定之後才校對、翻譯字幕；校對後要改剪輯，先告訴使用者校對過的內容要重做」。根本原因是字幕和片段沒有連結（剪輯一改，字幕時間就全部錯開），備份只保住內容、不能搬到新時間。之後要升級成「改剪輯時保留校對內容」，列在工作地圖的「功能」

## 修訂紀錄
規格同意之後才發現要改的地方記在這裡。內文直接改成新內容，
並在改過的地方加上「（YYYY-MM-DD 修訂，見修訂紀錄）」。

### 2026-10-10：驗證時發現（實作後補記，待使用者確認）
| # | 發現了什麼 | 原因 | 怎麼改 |
|---|---|---|---|
| 1 | EDL 的 `subtitles` 本來就是 `master.srt` 時（SKILL.md 範例的寫法）也跳出「會被忽略」的警告 | 規格寫「EDL 有 `subtitles` 就警告」，沒想到指向的就是重新產生的那個檔案 | 只在指向**別的**檔案時警告；指向 `master.srt` 本身時不算忽略，舊內容不同時由備份保住 |
| 2 | 訊息顯示 `master SRT → master.srt.tmp`，看起來像輸出檔叫這個名字 | 先寫暫存檔再換上 | 訊息改成顯示最後的檔名 `master.srt` |

- 範圍有沒有變：沒有
- 「不能改動的地方」是否仍然成立：成立。main 和新程式產生的字幕逐位元組相同（`ja` 16:9；`zh-tw` podcast 16:9、直式 `--sub-max-chars 10`、直式自動），完整算繪（`--draft --build-subtitles`）正常
