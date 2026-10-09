# 日文逐字稿不被當成中文：實作計畫
對應規格：specs/2026-10-09-ja-not-chinese.md

## 步驟（給我看）
1. 先寫測試：加 3 個日文的測試，執行後應該失敗（證明測試抓得到現在的錯誤）
2. 改程式：`looks_chinese()` 加上「日文標記」和「有假名」兩道檢查
3. 驗證：全部測試通過；用真的 podcast 逐字稿確認中文仍判斷為中文

## 細節（給 Agent）
### 步驟 1
- 修改的檔案和位置：`tests/test_render_captions_zh.py` 的 `LooksChineseTests`
- 做法：新增
  - `test_japanese_language_code`：`ja`、`jpn` 搭配漢字很多的日文 words（例如「東京大学で医学研究会議に参加」逐字一個 token）→ `False`
  - `test_kana_without_language_code`：沒有 `language_code`、同一份日文 words → `False`
  - `test_kana_with_other_language_code`：`language_code` 為 `eng`、同一份日文 words → `False`（Scribe 標錯時也不當中文）
- 執行 `uv run --with pytest python -m pytest tests/test_render_captions_zh.py -q`，預期這 3 個失敗、其他通過

### 步驟 2
- 修改的檔案和位置：`helpers/zh_text.py` 的 `looks_chinese()`
- 做法：
  - 語言標記以 `zh`／`cmn`／`yue` 開頭 → `True`（不變）
  - 語言標記是 `ja` 或 `jpn` → `False`
  - 其他情況（沒有標記，或標記是其他語言）看文字：出現平假名或片假名（U+3040–U+30FF）→ `False`；否則照舊用漢字比例
  - 新增的註解用繁體中文；docstring 補一句日文的處理

### 驗證
- 執行指令：`uv run --with pytest python -m pytest -q`（全部測試）
- 預期結果：原有 105 個 + 新增 3 個全部通過
- 真資料：對 `podcast_test/edit/transcripts/podcast_0935-1540.json` 呼叫 `looks_chinese()` → `True`（只讀取，不重新打包、不覆蓋 `takes_packed.md`）
