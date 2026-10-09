# XML 匯出：AI 粗剪交給 DaVinci 細剪
日期：2026-10-08　狀態：已同意

## 給我看的（白話，10 行以內）
- 要做什麼：新增 `export_xml.py`，把 `edl.json`（AI 的剪輯決定）轉成 DaVinci 讀得懂的剪輯清單 `timeline.xml`（Final Cut Pro 7 XML，一種很多剪輯軟體都能讀的時間軸格式）
- 為什麼：現在只有壓扁的 mp4，剪掉的部分找不回來。XML 指向原始素材，剪輯師可以在時間軸上拉長、縮短每一刀
- 怎麼做：第一條影像軌放剪好的片段，第二條影像軌放問題卡（PNG 圖片），聲音跟著片段走；字幕不放進 XML，另外匯入 `master.srt`
- 不做什麼：不帶淡入淡出、調色、音量標準化（剪輯師在 DaVinci 收尾）；不改 render.py；只驗證 DaVinci，不驗證 Premiere
- 怎樣算完成：DaVinci 匯入後，片段數量、順序、起訖點和 v3 一致；拉長任一段看得到被剪掉的畫面；問題卡時間正確；SRT 匯入後字幕對得上。Claude 會提供逐步操作說明和對照表

## 給 Agent 的（細節）
- 會影響的檔案：
  - 新增 `helpers/export_xml.py`：`export_xml.py <edl.json> -o <timeline.xml>`，預設輸出在 EDL 同一個資料夾
  - 新增 `tests/test_export_xml.py`
  - `SKILL.md` 的 Helpers 清單加一行說明（和官方版的差異，記進 `decisions.md`）
- 不能改動的地方：`render.py`、EDL 格式（只讀不寫）、現有測試
- 技術細節：
  - 格式：`<xmeml version="5">` → `sequence` → `media` → `video`（V1 片段、V2 問題卡）+ `audio`（每個聲道一條軌）
  - 時間：秒數換成影格。素材幀率用 ffprobe 讀（這支是 24000/1001 → `timebase=24`、`ntsc=TRUE`）；起點 `round(start * fps)`，終點 `round(end * fps)`，時間軸位置用累加的影格數，避免四捨五入誤差累積
  - 每段片段：`clipitem` 的 `in`/`out` 是素材上的影格，`start`/`end` 是時間軸上的影格；`name` 用 EDL 的 `beat`（「A1 找原因」），方便在 DaVinci 裡對照
  - 同一個來源檔只定義一次 `file`（`id` 重複引用）；`pathurl` 用 `file://localhost/C:/...`，非 ASCII 字元做 percent-encode
  - `file` 要寫素材的總長度、寬高、幀率、聲道數、取樣率（ffprobe），DaVinci 才能允許拉長到片段以外；另外要寫起始時間碼 `<timecode>`（固定 `00:00:00:00`、NDF），DaVinci 才接得上聲音片段（2026-10-09 修訂，見修訂紀錄）
  - 影像和聲音 `clipitem` 用 `link` 互相連結，拖動時一起移動
  - 問題卡：EDL `overlays` 的 `file` 若是 `.mov`，找同名 `.png`（`cards/q1.png`）；有 PNG 就當成靜態圖片放在 V2，長度用 `duration`；找不到 PNG 就照原檔放並印出警告
  - 序列設定用來源的寬高與幀率（1280×720、23.976），不放大到 1080p
  - 字幕：只在終端機印出提示「到 DaVinci 用 File → Import → Subtitle 匯入 `master.srt`」
  - 不輸出：`grade`、30ms 音訊淡入淡出、loudnorm、問題卡淡入淡出
- 驗證：
  - 自動測試：用假的 EDL（兩個來源、三段、一個 overlay）檢查影格換算、時間軸累加、`file` 只定義一次、percent-encode、PNG 替換
  - 實機：在 DaVinci 21.1 免費版匯入 `podcast_test/edit/timeline.xml`。對照方式：
    1. Claude 產生對照表（每段的名稱、時間軸起點、素材起訖時間碼），使用者在 DaVinci 時間軸上逐段點選比對
    2. 從 DaVinci 匯出時間軸 XML（File → Export → Timeline），Claude 讀回來和原本的 XML 比對數字
    3. 抽 2–3 個剪接點，和 `versions/v3/preview.mp4` 對看畫面
  - 媒體離線（片段變紅）時：先懷疑中文路徑（`C:\Users\長\...`），把素材複製到英文路徑（例如 `C:\video_test\`）重新匯出再試

## 修訂紀錄
規格同意之後才發現要改的地方記在這裡。內文直接改成新內容，
並在改過的地方加上「（YYYY-MM-DD 修訂，見修訂紀錄）」。

### 2026-10-09：`file` 加上起始時間碼
- 發現：DaVinci 21.1 匯入 `timeline.xml` 後，V1 畫面正常，A1、A2 聲音片段全部離線（紅色）。匯入紀錄對每個聲音片段都寫「File not found in search directories」。原始檔在 DaVinci 裡播放有聲音（Clip Attributes：1 條立體聲軌）
- 參考：在 DaVinci 用原始檔建時間軸、匯出 FCP 7 XML，和我們的 XML 比對，聲音相關的差異有三個：聲道軌數（1 條立體聲 vs 2 條單聲道）、`file` 的 audio 有沒有寫取樣率、`file` 有沒有 `<timecode>`
- 實驗：每份只改一處，在同一個專案匯入（`podcast_test/edit/xml_tests/`）

  | 測試檔 | 改了什麼 | 聲音 |
  |---|---|---|
  | test_0 | 不改（對照組） | 離線 |
  | test_a | 只留 1 條立體聲軌 | 離線 |
  | test_b | 拿掉 audio 的取樣率、位元深度 | 離線 |
  | test_c | `file` 加 `<timecode>` 00:00:00:00 | 正常 |

- 結論：缺時間碼是原因；聲道寫法（每聲道一條軌）DaVinci 可以接受，不用改
- 不處理：素材本身帶時間碼的情況（攝影機檔案，例如 `14:23:10:00`），固定寫 `00:00:00:00` 可能又對不上。目前沒有這類素材可以實測，留到之後

### 2026-10-09：DaVinci 實機驗證結果
- 修正後匯入：V1 8 段、V2 3 張問題卡、A1/A2 聲音都正常，總長 `00:02:18:09`；最後一段可以往右拉長，看得到剪掉的畫面
- 從 DaVinci 匯出 `davinci_export.xml` 和 `timeline.xml` 比對：序列長度、每條軌的片段數、每段的 `start`/`end`/`in`/`out`、來源檔全部一致（0 個差異）
- 和預期不同但不影響使用：
  - DaVinci 時間軸上的片段名稱顯示成檔名（`podcast_0935-1540.mp4`），不是 EDL 的 `beat`（「A1 找原因」）；聲音片段離線時才會顯示 `beat`。逐段對照改用時間碼
  - DaVinci 匯出時 A2 的 `sourcetrack` 寫成 1（我們寫 2），聲像都是置中。左右聲道是否正確分開沒有實測
