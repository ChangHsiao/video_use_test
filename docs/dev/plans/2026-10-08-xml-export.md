# XML 匯出：實作計畫
對應規格：specs/2026-10-08-xml-export.md

## 步驟（給我看）
1. 你從 `main` 開新分支 `feat/xml-export`（我給指令）。
2. 先寫測試，用假的剪輯清單檢查換算結果。這時執行會失敗，因為程式還沒寫。
3. 寫 `export_xml.py`，讓第 2 步的測試全部通過，舊的測試也不能壞。
4. 用 `podcast_test` 實際產生 `timeline.xml`。我先自己檢查：讀回 XML，逐段和 `edl.json` 對數字，並做一份對照表給你。
5. SKILL.md 加一行介紹新工具；`decisions.md` 新增這次的決定（為什麼選這個格式、為什麼問題卡用 PNG）。
6. 你在 DaVinci 匯入 XML 和字幕，照我寫的逐步說明操作，用對照表比對；再從 DaVinci 匯出一份 XML 給我比對數字。片段變紅（找不到素材）就改用英文路徑重試。
7. 你看過 diff 後，我給 commit 指令。

第 2～5 步每做完一步，我會停下來說明改了什麼，讓你看 diff。

## 細節（給 Agent）

### 步驟 1：開分支（由使用者執行）
- 在 `.claude/skills/video-use/` 執行：
  - `git switch main`
  - `git status`（應該只有未追蹤的 `docs/dev/specs/2026-10-08-xml-export.md` 和這份計畫；它們會在步驟 7 跟程式一起 commit）
  - `git switch -c feat/xml-export`
- 確認：`git branch --show-current` 印出 `feat/xml-export`。

### 步驟 2：測試先行
- 新增 `tests/test_export_xml.py`，照 `test_render_fps.py` 的方式用 `importlib` 依路徑載入 `helpers/export_xml.py`。
- 不呼叫 ffprobe：`build_xmeml()` 接受 `probe` 參數，測試傳入假的 probe 函式（回傳固定的幀率、長度、寬高、聲道）。
- 測資：兩個來源（其中一個路徑含中文）、三段 range、一個 overlay（`.mov`，旁邊有同名 `.png`）。
- 測試案例：
  - 幀率對應：`24000/1001` → `timebase=24`、`ntsc=TRUE`；`30000/1001` → `30`、`TRUE`；`25/1` → `25`、`FALSE`
  - 秒數換影格：`in = round(start * fps)`、`out = round(end * fps)`
  - 時間軸位置：第 n 段的 `start` = 前面各段 `out - in` 的總和（用影格累加，不用秒數）；`end = start + (out - in)`
  - 同一個來源檔只有一個完整的 `<file>`（有 `pathurl`），其他 clipitem 只用 `<file id="..."/>` 引用
  - `pathurl`：`file://localhost/C:/...` 開頭，中文 percent-encode（`長` → `%E9%95%B7`），斜線和磁碟機冒號不編碼
  - clipitem 的 `name` 用 EDL 的 `beat`；沒有 `beat` 時用 `<source> <n>`
  - 影像和聲音 clipitem 之間有 `<link>`
  - overlay：`.mov` 旁邊有 `.png` 時，V2 用 PNG、有 `<stillframe>TRUE</stillframe>`；時間軸位置是 `round(start_in_output * fps)`，長度是 `round(duration * fps)`
  - 找不到 PNG 時照原檔放，並在 stderr 印警告
  - 輸出可以被 `xml.etree.ElementTree` 解析，根節點是 `xmeml`、`version="5"`
- 執行並確認失敗原因是「檔案不存在」，不是測試寫錯。

### 步驟 3：`helpers/export_xml.py`
- 函式：
  - `probe_media(path) -> dict`：`ffprobe -print_format json -show_streams -show_format`，回傳 `fps`（`Fraction`）、`duration_s`、`width`、`height`、`audio_channels`、`sample_rate`。圖片（PNG）只需要寬高。
  - `fps_to_rate(fps: Fraction) -> (timebase: int, ntsc: bool)`：分母是 1001 → `(round(fps), True)`；整數 → `(fps, False)`；其他 → 四捨五入、`False`，並印警告。
  - `path_to_url(path: Path) -> str`：`"file://localhost/" + quote(path.resolve().as_posix(), safe="/:")`
  - `build_xmeml(edl: dict, edl_dir: Path, probe=probe_media) -> ElementTree`
  - `main()`：`export_xml.py <edl.json> [-o <timeline.xml>]`，預設輸出在 EDL 同一個資料夾。
- 結構：
  - `xmeml` → `sequence`（`name` = EDL 所在的影片資料夾名稱；`rate`、`format/samplecharacteristics` 用第一個來源的幀率和寬高；`duration` = 總影格數）
  - `media/video`：`track` 1 = 剪輯片段，`track` 2 = 問題卡
  - `media/audio`：來源每個聲道一條 `track`（最多 2），clipitem 用 `sourcetrack/trackindex` 對應聲道
  - clipitem 的 `duration` 寫來源總影格數，`in`/`out` 寫素材上的影格（DaVinci 才知道片段前後還有素材可以拉）
  - `<file>`：`name`、`pathurl`、`rate`、`duration`、`media/video/samplecharacteristics`（寬高）、`media/audio`（`samplecharacteristics/samplerate`、`channelcount`）
  - id 規則：`file-<n>`、`clip-v-<n>`、`clip-a<ch>-<n>`、`card-<n>`
- 檔案開頭寫 `<?xml version="1.0" encoding="UTF-8"?>` 和 `<!DOCTYPE xmeml>`，用 `ElementTree.indent()` 排版。
- 結束時印出：片段數、總長度、問題卡數；EDL 有 `subtitles`（或資料夾裡有 `master.srt`）時，提示「到 DaVinci 用 File → Import → Subtitle 匯入」。
- 不讀：`grade`、`total_duration_s`。
- 驗證：`uv run --project . python -m unittest discover -s tests` 全部通過（在 `.claude/skills/video-use/` 執行）。

### 步驟 4：實際產生並自我檢查
- 執行：`uv run --project .claude/skills/video-use python .claude/skills/video-use/helpers/export_xml.py podcast_test/edit/edl.json`
- 輸出：`podcast_test/edit/timeline.xml`（新檔案，不會覆蓋其他檔案）
- 自我檢查（scratchpad 腳本，不進 repo）：讀回 XML，把每段的 `in`/`out` 換回秒數，和 `edl.json` 比對，誤差要小於 1 格（約 0.042 秒）；時間軸總長度和 `versions/v3/preview.mp4` 的長度相差不超過 2 格。
- 產生對照表 `podcast_test/edit/timeline_check.md`：每段的名稱、時間軸起點（時間碼）、素材起訖（時間碼），加上 3 張問題卡的起點和長度。時間碼用 `HH:MM:SS:FF`，和 DaVinci 顯示的一樣。

### 步驟 5：文件
- `SKILL.md` 的 Helpers 清單，在 `render.py` 後面加一行（英文）：`export_xml.py <edl.json>` → `timeline.xml`（FCP 7 XML）給 DaVinci / Premiere 接手細剪：V1 片段連到原始素材、V2 問題卡用 PNG、字幕另外匯入 `master.srt`；不帶調色、淡入淡出和音量標準化。
- `decisions.md` 新增：
  - 匯出格式用 Final Cut Pro 7 XML。原因：DaVinci、Premiere 都能讀，可以表達多軌和素材總長度。其他選項：CMX3600 EDL（只有單軌剪輯點）、新版 FCPXML（Premiere 不能讀）、OpenTimelineIO（要多裝套件）
  - 問題卡在 XML 裡用 PNG。原因：DaVinci 免費版不一定能解 qtrle；PNG 一定能讀。其他選項：直接引用 `.mov`
  - SKILL.md 加入 `export_xml.py` 的說明，和官方版產生差異。原因：不寫的話，AI 不知道有這個工具

### 步驟 6：DaVinci 實機驗證（使用者操作，Claude 寫逐步說明）
- 說明內容：開新專案 → File → Import → Timeline → 選 `timeline.xml`（保留「自動設定專案」，讓專案變成 1280×720、23.976）→ 素材找不到時的處理 → File → Import → Subtitle 匯入 `master.srt`，拖到字幕軌 → 照對照表點選片段比對 → 把一段的尾巴往右拉，確認看得到被剪掉的畫面 → File → Export → Timeline 匯出 FCP 7 XML 給 Claude。
- Claude 比對匯出的 XML：片段數、每段 `in`/`out`、時間軸位置。
- 媒體離線（片段變紅）：把 `podcast_0935-1540.mp4` 和 `cards/*.png` 複製到 `C:\video_test\`，用暫時改過路徑的 EDL 副本重新匯出（不改 `edit/edl.json`）。這是繞道方法，結果要記進規格的修訂紀錄。
- 抽 2–3 個剪接點，和 `versions/v3/preview.mp4` 對看畫面。

### 步驟 7：提交（由使用者執行）
- 照 `git-commit-guide.md` 的格式和目前的學習階段，由使用者決定 commit 類型。
- 同一個 commit：`helpers/export_xml.py`、`tests/test_export_xml.py`、`SKILL.md`、`docs/dev/decisions.md`、這份規格和計畫。
- `podcast_test/` 不在 repo 裡，不用 commit。

### 驗證
- 執行指令：`uv run --project . python -m unittest discover -s tests`（在 `.claude/skills/video-use/`）
- 預期結果：新舊測試全部通過；`timeline.xml` 在 DaVinci 匯入後符合規格的「怎樣算完成」。
