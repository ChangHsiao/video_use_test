# 決策紀錄

**收錄標準**：看到專案現在的樣子，未來的自己或 Agent 會不會問「為什麼是這樣？」會的話就記一行。
這台電腦的環境設定寫在 `CLAUDE.md`，工作方式和偏好寫在 `workflow.md`，不放這裡。

只新增，不修改舊的紀錄；決定改變時，新增一行說明新的決定。

| 日期 | 決定 | 原因 | 考慮過的其他選項 |
|---|---|---|---|
| 2026-10-04 | 先用原版的 ElevenLabs Scribe 轉錄，之後再加上 Whisper 切換 | 先熟悉原版流程；Whisper 會吃掉 umm、uh 等贅詞，時間戳也比較不準 | 直接改用 Whisper |
| 2026-10-04 | OpenAI 的轉錄選項用 `whisper-1` | OpenAI 的模型中，只有它提供逐字時間戳 | `gpt-transcribe`、`gpt-4o-transcribe-diarize` |
| 2026-10-04 | A/B test 時，兩種轉錄服務用不同的 `--edit-dir` | 逐字稿有快取，同一個資料夾會讓第二次直接讀到第一次的結果 | 在逐字稿檔名加上服務名稱 |
| 2026-10-04 | 自建 private repo 當 `origin`，官方 repo 設為 `upstream` | public repo 的 fork 不能設成 private | GitHub Fork |
| 2026-10-04 | commit `uv.lock`（官方 repo 沒有） | 固定套件版本，讓 A/B test 的環境一致 | 不 commit，每次安裝最新版 |
| 2026-10-04 | 採用七步工作流加上文件驅動開發（規格、計畫、決策紀錄） | 可以追溯決定的原因，Agent 也有執行依據 | 不寫文件；完整套用 superpowers 的流程 |
| 2026-10-04 | 字幕語言由 Claude 看逐字稿決定並傳入 `--sub-lang`；render.py 只發出警告，不自動切換 | Claude 比程式更會判斷中英夾雜的影片；預設維持 `en`，不改變官方原本的行為 | render.py 依 `language_code` 自動切換 |
| 2026-10-04 | Windows 相容性修正（UTF-8 編碼、字幕路徑改用正斜線）放在繁中字幕分支 | 以自己的專案進度為主；不修的話本機無法渲染，第二階段無法測試 | 另開規格和分支，方便以後送回官方 repo |
| 2026-10-04 | 中文字幕測試另開新檔 `test_render_captions_zh.py` | 不改官方的測試檔，合併官方更新時比較不會衝突 | 加在 `test_render_captions.py` 裡 |
| 2026-10-04 | 簡繁轉換（OpenCC）延後，等真影片實測後再決定 | Scribe 可能直接輸出繁體，先不增加套件依賴 | 一開始就加入 OpenCC |
| 2026-10-06 | 中文字幕和 `takes_packed.md` 用 OpenCC `s2twp` 轉成台灣繁體（取代 2026-10-04「OpenCC 延後」） | 實測 Scribe 輸出的是簡體；`s2twp` 連用語一起轉（视频 → 影片） | 不轉換，請使用者自己改；`s2t`（只轉字形，不轉用語） |
| 2026-10-06 | 中文字幕只在 jieba 判斷的詞邊界斷句 | Scribe 一個字一個 token，停頓和寬度上限會把詞切開（全 / 力、傷 / 得） | 只靠停頓和標點斷句 |
| 2026-10-06 | jieba 和 OpenCC 放在主要依賴，但第一次用到時才載入 | 安裝簡單，`uv sync` 就有；英文影片不會載入，不拖慢速度 | 放在 optional-dependencies |
| 2026-10-06 | `pack_transcripts.py` 自動判斷中文，不加參數 | 和 `render.py` 共用 `looks_chinese()`；英文輸出完全不變 | 加 `--lang` 參數 |
| 2026-10-08 | 剪輯專案檔的匯出格式用 Final Cut Pro 7 XML（新增 `export_xml.py`） | DaVinci、Premiere 都能讀；能表達多軌（片段、問題卡、聲音）和素材總長度，剪輯師才能把剪掉的部分拉回來 | CMX3600 EDL（只有單軌剪輯點）、新版 FCPXML（Premiere 不能讀）、OpenTimelineIO（要多裝套件） |
| 2026-10-08 | 問題卡在 XML 裡改用同名的 PNG，不用算繪時的 `.mov` | DaVinci 免費版不一定能解 qtrle 編碼的 `.mov`；PNG 一定能讀，在時間軸上也能直接調整長度 | 直接引用 `.mov` |
| 2026-10-08 | SKILL.md 的 Helpers 清單加入 `export_xml.py`，和官方版產生差異 | SKILL.md 是 AI 讀的說明，不寫的話 AI 不知道有這個工具可以用 | 只寫在 README，不改 SKILL.md |
