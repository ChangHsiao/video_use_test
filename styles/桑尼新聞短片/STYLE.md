# 風格：桑尼新聞短片

| 項目 | 內容 |
|---|---|
| 適用範圍 | 桑尼資料科學（Sunny Data Science）的直式新聞解說短影音，用於 YouTube Shorts 和 Reels。結構是「旁白鋪陳 → 原聲佐證」交替，片長約 2 分鐘 |
| 品牌 | CIS 在 `brand/`，Logo 在 `brand/logo_main_1x1.png` 和 `brand/dark.svg` |
| 研究依據 | 參考短片拆解：[研究_參考短片拆解.md](研究_參考短片拆解.md)<br>封面、標題、片尾的中美研究：[研究_封面標題片尾.md](研究_封面標題片尾.md)<br>聲音規格：[錄音室規格.md](錄音室規格.md) |
| 範例 | `D:\videos\黃仁勳辭任\edit\short_v6.mp4`（EP.01），分鏡寫在同一層的 `短片.json` |
| 狀態 | 第一版，2026-11-20 |

## 怎麼用

1. 把 `tools/` 複製到 `<影片資料夾>/edit/tools/`。工具以上一層的 `edit/` 當工作目錄；Logo 和字型會先找影片資料夾內的，找不到就讀這個風格資料夾的。
2. 寫 `edit/voice/台詞_short.txt`。格式是 `句號|念的文字|字幕中文|字幕英文`，用 `## 段名` 分段，每段是一個旁白區塊。
3. 產生配音：
   ```
   python prosody.py --voice-dir D:/videos/聲音範本/A1_男聲 --tag short_A1 --profile news --script ../voice/台詞_short.txt --sections 0,1,...
   ```
4. 檢查配音：`python vocal_qc.py ../voice/錄音室版/short_A1_rhythm.mp3`，每一項都要是 OK。
5. 寫分鏡 `edit/短片.json`（格式見 `tools/short.py` 開頭的說明），然後算繪：`python tools/short.py 短片.json --out short_vN.mp4`。
6. 交片前做審稿（見下方「審稿」），並寫好發布資料（見下方「發布資料」）。

## 固定的規則

### 版面

以 1080×1920 為準，數值從參考短片量測後放大 2.25 倍。

| 項目 | 規則 |
|---|---|
| 背景 | 同一個鏡頭放大、模糊、壓暗，鋪滿全畫面 |
| 主畫面帶 | y 327–1250，下緣 300px 漸層到黑 |
| 人物取景 | 自動偵測臉部：單人時置中；多人放不下時改成整個畫面完整顯示，旁邊用模糊底填滿。不准用硬裁切把人的肢體切掉 |
| 新聞台跑馬燈 | 裁掉來源畫面下方 27% |
| 固定標題 | y ≈ 300，置中，46px 粗體白字，關鍵詞用薄荷綠 |
| 資訊卡 | y 1080：紅底白字標籤、細線，下接兩行 32px 白字，背後墊半透明深色底 |
| 原聲卡 | y 1255：紅底寫「原聲｜人名、職稱」，下接一行小字出處 |
| 雙語字幕 | 中文 52px 薄荷綠粗體，放在 y 1350；英文 32px 白字，放在中文下方 |
| 字幕的長度 | 一句太長就縮小字級，再長就斷成兩行 |
| 原聲字幕 | 依逐字時間切成 1–3 秒一句，跟著講者即時切換，中文在上、英文原文在下 |

### 配色與字體（CIS）

| 用途 | 色彩 |
|---|---|
| 字幕、重點字 | 薄荷綠 `#7EEBD9`（Logo 色） |
| 標籤、線條、轉場 | 紅色 `#BA4D43`（Featured Red） |
| 主色、系列條 | 青綠 `#2C918C` |
| 底色 | `#050505`、`#0F2D2B` |

字體：中文用 Noto Sans TC，英文用 Inter（在 `fonts/`）。

不使用 CIS 以外的顏色。參考短片原本用黃色字幕，這裡改成薄荷綠。

### 畫面質感

- **調色**：對比 1.07、飽和 0.86，暗部偏冷、亮部偏暖。
- **整體**：最後加暗角和細顆粒。
- **推近**：旁白段的畫面緩慢推近 4%；原聲段不推近，避免干擾講者。

### 節奏與轉場

| 項目 | 規則 |
|---|---|
| 旁白語速 | 對齊參考短片：含停頓約 5.6–6.0 音節/秒，停頓中位數 0.4 秒（`--profile news`） |
| 同段內換畫面 | 溶接 0.3 秒，切點放在句與句之間停頓的中點 |
| 段落之間 | 溶接 0.45 秒 |
| 原聲片段 | 前留 0.35 秒、後留 0.5 秒，聲音淡入淡出 |
| 段尾 | 每段旁白結束後留 0.6 秒 |

### 片頭封面（系統 C：系列問題卡）

封面就是影片第一幀，停留 1.2 秒，期間不疊字幕。Shorts 的動態牆會直接播放，觀眾看到的是第一幀，不是另外上傳的封面。

| 元素 | 規則 |
|---|---|
| 系列條 | 青綠橫條，白字「科技大事 2 分鐘」，放在頂部約 16% 處 |
| 大字 | 三行、每行約 4 字，靠左；第三行用薄荷綠，下方一條紅色短線 |
| 人物 | 用**真實的新聞照或官方影像**，表情平穩，放右下 |
| 品牌 | Logo 加「桑尼資料科學」 |
| 不放 | 集數（EP）。理由：每支新聞短片都能獨立看，集數對新觀眾沒有資訊，反而暗示要先看前面幾集；集數放在播放清單和說明欄就好 |

**AI 設計流程**（Higgsfield MCP，模型 `gpt_image_2_6`，9:16、high、2k，兩張約 5.5 credits）：

1. 上傳兩張參考圖：真實人物照片和 `brand/logo_main_1x1.png`。上傳時要帶 `User-Agent: curl/...`，不然會被 Cloudflare 擋（錯誤碼 1010）。
2. 用下方的提示詞。範例成品：`assets/cover_example_ai.png`。
3. 檢查兩件事：人物的臉是否走樣（新聞類寧可用去背的原照，AI 只做背景和版面），以及有沒有東西壓進安全區外。

提示詞範本（`{}` 處換成本集內容）：

```
Vertical 9:16 YouTube Shorts cover for a Taiwanese tech-news explainer series. Premium editorial design, calm and credible, not clickbait.
PERSON: Use the person from reference image 1 exactly as photographed: same face, expression, clothing and pose. Do not alter identity, features or expression. Cut out cleanly, place in the lower-right area but keep the right 12% of the frame clear, waist-up, about 50% of the frame height. Subtle mint (#7DE4D3) rim light.
BACKGROUND: near-black (#050505) blending to dark teal (#0F2D2B), faint teal (#2C918C) dot grid and thin circuit lines, subtle depth.
TYPOGRAPHY (Traditional Chinese, heavy sans-serif like Noto Sans TC Black, perfectly rendered):
- Teal (#2C918C) bar at ~16% from top with white text "科技大事 2 分鐘".
- Headline left-aligned between 22% and 50% height, three lines: "{第一行}" white, "{第二行}" white, "{第三行}" mint #7DE4D3, short thick brick-red (#BA4D43) underline below line 3.
- Logo from reference image 2 as a small rounded square plus white text "桑尼資料科學", at ~70% height on the left (above the bottom 20%).
No other text, no English, no episode number, no emojis, no watermark.
```

**安全區**：上方 15%、下方 20%、右側 12% 會被 Shorts 介面遮住。大字只能放在 y 300–1500、x 80–940 之間。

### 片尾（A 數據流，3 秒）

- 檔案：`assets/outro_A_3s.mp4`，由最後一個鏡頭溶接進來。
- 動畫內容：Logo 線條自己描繪、填色、點亮眼睛；品牌名稱出現，英文字距展開；標語「用數據，看懂科技大事。」；追蹤、按讚、分享三個線條圖示依序畫出；最後是「每週拆解一則科技大事」。
- 原始碼：`remotion/outro/`。要改文字或長度時：
  - 把這個資料夾複製進 Remotion 專案的 `src/outro/`。
  - 在 Root 註冊 `O1`（4 秒），以及 `<O1 speed={4/3} />`（3 秒）。
- 研究結論：Shorts 的片尾要短。重播也算觀看次數，片尾太長，觀眾會在片尾滑走。不要只喊「記得訂閱」，要說觀眾能得到什麼。

### 口播收尾（聲音標誌）

- 每集最後一句旁白是固定的收尾口號，**一次錄好、每集都用同一個檔案**，不能每集重新生成。理由：每次生成的語氣都不一樣，就形不成記憶點。
- 錄製：`tools/signoff.py`，用較穩定的設定：stability 0.65、speed 0.98、固定 seed。
- 定版（2026-11-20）：「這裡是桑尼資料科學，每週用數據，拆解一則科技大事。」，A1 男聲，5.0 秒，檔案 `assets/signoff.wav`。
- 用法：在分鏡最後加一個 `{"signoff": {"audio": ..., "show": ..., "en": ...}, "shots": [...]}` 區塊，台詞檔不寫這句。
- 收尾後**不再加**「喜歡請按讚、追蹤、訂閱、分享」的口播。理由：會讓片尾多出 2–3 秒沒有內容的時間，觀眾容易滑走，也打斷循環播放；片尾動畫已經用圖示呈現這三件事。要引導互動，就在收尾前放本集提問。
- 發片頻率如果改成每天，要重錄這一句，承諾和實際頻率必須一致。

## 預設值

| 項目 | 預設值 |
|---|---|
| 旁白聲音 | A1 男聲 `CG56nF519jHs9bMWKdXk`；B1 女聲 `gGmJOmvg7PPQJ8AkL8Yd`。範本在 `D:\videos\聲音範本\` |
| 配音後製 | 錄音室規格：−16 LUFS、換氣比人聲低 24–30 dB、底噪 ≤ −65 dBFS |
| 配樂 | `assets/music_bed_news.mp3`。開場比人聲低約 20 dB，最後 25 秒逐漸升起 |
| 片中固定標題 | 封面大字縮成一行，例如「一段私事，怎麼變成\|國安疑雲」（`\|` 之後是要上重點色的字） |
| YouTube 片名 | `{說明句，不加問號}：{事件＋關鍵事實}｜科技大事 2 分鐘 #Shorts`。重要字放在前 40 字內；不用問號、不用「震驚」這類字眼 |

## 審稿（必做）

成片交給使用者之前，派一個審稿 sub-agent，逐鏡頭抽格檢查：

1. 畫面和旁白是否對得上。
2. 隱私與指控：當事人中不該露臉的人不能出現，也不能被點名；指控一定要寫明出處，例如「據報導」「被懷疑」。新聞台的跑馬燈如果把指控寫成事實，要裁掉。
3. 關鍵句前後：講到「那名女子」「高階主管」這類字眼時，畫面上不能剛好出現身分不明的人，觀眾會誤認。
4. 字卡和來源畫面的字有沒有互相壓到。
5. 原聲字幕和講話是否同步。

EP.01 抓出來的嚴重問題，都屬於第 3 項。

## 發布資料

格式參考 `D:\videos\黃仁勳辭任\edit\design\發布資料.md`：

- 片名
- 說明欄：
  - 一段話摘要，每項指控都寫出處
  - 本集提問
  - 註記：指控未經證實、動畫為示意圖
  - 系列句
  - 原聲與畫面來源（每支來源影片的 YouTube 標題和網址）
  - 資料來源
  - hashtag
- 置頂留言：放本集提問，不用表情符號
