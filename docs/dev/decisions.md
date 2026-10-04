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
