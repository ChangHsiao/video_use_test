# 中文字幕：配合畫面寬度斷句：實作計畫
對應規格：specs/2026-10-09-zh-tw-vertical-captions.md

## 步驟（給我看）
1. 你開分支 `feat/zh-tw-vertical-captions`（我給指令）
2. 字數上限依畫面寬度計算：render.py 產生字幕前先量影片尺寸，直式約 10 字、橫式維持 14 字
3. 超過上限時挑切點：標點 → 停頓 → 詞邊界；數字和單位不拆、標點不放句首
4. 說話者換人一定斷句 (b)；不到 0.8 秒的句子併入前後句 (c)
5. 句首標點刪掉 (a)；句中標點換成 En space (d)
6. 每一步都先寫測試、再改程式，跑全部測試；改完更新 SKILL.md 和 decisions.md
7. 實測：用 skill 直接產生直式和橫式 v3 的字幕，截圖對照 9 個問題，並確認沒有一句被折行
8. 你看過 diff 和實測結果後，我給 commit 指令

## 細節（給 Agent）
### 步驟 1：開分支
- 指令（使用者在 `.claude/skills/video-use/` 執行）：`git switch -c feat/zh-tw-vertical-captions`
- 基準：`main` 在 8725257，`uv run python -m unittest discover -s tests` → 75 個測試通過

### 步驟 2：上限依畫面寬度
- 修改的檔案和位置：`helpers/render.py`
  - 新增 `zh_max_width(width, height) -> int`：`n = floor(width * 0.95 / (0.75 * 18 * height / 288)) - 1`，回傳 `min(ZH_CHUNK_MAX_WIDTH, 2 * n)`（下限 8，避免極端尺寸）
  - `chunk_words_zh(words, max_width=ZH_CHUNK_MAX_WIDTH)`：用參數取代常數
  - `build_master_srt(..., max_width=None)`：只在 `zh-tw` 時傳給 chunk 函式；`None` 時用 28（舊呼叫方式相容）
  - `main()`：`--build-subtitles` 且 `zh-tw` 時，ffprobe `base_path` 的寬高（沿用 `is_portrait_source` 的 ffprobe 寫法，考慮旋轉），算出上限傳入，並印出 `zh caption width cap: N`
- 測試：`zh_max_width(1080, 1920) == 20`、`(1920, 1080) == 28`、`(1080, 1080) == 28`；`chunk_words_zh(..., max_width=20)` 每句寬度 ≤ 20；`build_master_srt` 不傳時行為和現在一樣

### 步驟 3：切點選擇
- 修改的檔案和位置：`chunk_words_zh()` 裡的 `while ... > max_width` 迴圈；`helpers/zh_text.py` 新增 `is_number(text)`
- 做法：候選 k ∈ [start, i-1] 且 k 在 `bounds`、`words[start:k+1]` 寬度 ≤ 上限。排除：`words[k+1]` 是標點；`words[k]` 是數字且 `words[k+1]` 以中文字開頭。排序鍵 `(以 ZH_PUNCT_BREAK 結尾, gap ≥ 0.15, k)` 取最大；沒有候選時退回現行做法
- 測試（用實測的句子做測資）：「他們怎麼辦？他們會反映在自己的生理上嗎？」→ 問號不在句首；「不要 100 分，我 95 分可不可以」→「95」和「分」同一句；「跳出來看一下」不拆開「看 / 一下」以外的詞（只驗證切點在標點或停頓）

### 步驟 4：(b) 說話者換人、(c) 短句合併
- (b)：斷句條件加上 `nxt.get("speaker_id") != w.get("speaker_id")`（兩邊都有值時才比較）
- (c)：`chunk_words_zh` 回傳前掃一次：句子時長（最後一字 end − 第一字 start）< `ZH_CHUNK_MIN_S`，若和前一句同說話者且合併後寬度 ≤ 上限，併入前一句；否則同條件併入後一句；都不行就保留
- 測試：主持人「嗯。」+ 醫師句子 → 兩句；「光鮮亮麗」+「但是」（0.26 秒）→ 合併；併入後超過上限 → 不合併

### 步驟 5：(a) 句首標點、(d) 句中標點
- 修改的檔案和位置：`_format_cue_zh()`
- 做法：組好文字後去掉句首的 `ZH_PUNCT_BREAK` 字元與空白；句中（不含句尾）的 `，、；：。,;:` 換成 U+2002，並去掉它前後的空格；句尾照舊刪除（`？！` 保留）
- 測試：「，我覺得」→「我覺得」；「高壓環境下，然後他還很開心」→「高壓環境下 然後他還很開心」；「好用嗎？」不變；「Claude，你好」→ 不出現「空格＋U+2002」

### 步驟 6：文件
- `SKILL.md` 的 `zh-tw` 段落：上限改寫為「依輸出畫面寬度計算（橫式約 14 字、直式約 10 字）」；補上說話者換人斷句、短句合併、句中標點換成 En space
- `docs/dev/decisions.md` 新增：上限依畫面寬度；切點優先順序；句中標點用 U+2002（全形太開、半形太窄、兩個半形會被合併）；依意思斷句延後
- 規格狀態改成「已完成」

### 驗證
- 執行指令：
  1. `uv run python -m unittest discover -s tests` → 全部通過（75 + 新增）
  2. 直式實測：建立 `podcast_test/edit/vertical/skill_v2/`，複製 `edl.json` 和 `transcripts/`，執行 `render.py skill_v2/edl.json -o skill_v2/vertical_check.mp4 --build-subtitles --sub-lang zh-tw`。**不在 `vertical/` 直接跑**，因為 `--build-subtitles` 會覆蓋人工校對過的 `vertical/master.srt`。產生的是 16:9 影片，所以另外用 `zh_max_width(1080, 1920)` 產生直式字幕，再用 `scripts/compose.py` 的方式合成直式畫面
  3. 橫式實測：同樣方式在 `podcast_test/edit/horizontal_check/`（複製 v3 的 `edl.json`、`transcripts/`）產生字幕，和 `verify/rough1/master.auto.srt` 比較
- 預期結果：
  - 直式：每句寬度 ≤ 20；在 9 個問題的時間點截圖，除了 #6（口吃）都已解決；抽樣 10 個畫面沒有折行
  - 橫式：上限仍是 28；差異只來自 (a)～(d) 和切點選擇，沒有新的「詞被切斷」「標點在句首」
  - 實測完把截圖做成修正前後對照，給報告用

### 注意
- 直式驗證時，render.py 本身產生的是 16:9 畫面（裁切是臨時腳本做的），所以 `main()` 量到的是 1920×1080，上限會是 28。這是正確行為：skill 會照它實際輸出的畫面決定上限。直式的驗證要用 `build_master_srt(..., max_width=zh_max_width(1080, 1920))` 直接呼叫，計畫外的做法需要先停下來說明
