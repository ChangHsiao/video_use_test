# 風格：桑尼新聞短片

| 項目 | 內容 |
|---|---|
| 適用範圍 | 直式新聞解說短影音（YouTube Shorts、Reels）的畫面和節奏規則。結構是「旁白鋪陳 → 原聲佐證」交替，片長約 2 分鐘。給 Agent 做分鏡、配音、合成時照做 |
| 製作流程 | [sop/新聞短片.md](../../sop/新聞短片.md)（步驟、確認點、審稿、發布資料都在那裡） |
| 品牌 | [桑尼資料科學](../../brands/桑尼資料科學/BRAND.md)：CIS、logo、字型、片尾、口播收尾。`style.json` 用 `"brand": "桑尼資料科學"` 接上 |
| 給程式讀的數值 | `style.json`（版型 `news_band`，由 `helpers/news_short.py` 畫） |
| 研究依據 | 參考短片拆解：[研究_參考短片拆解.md](研究_參考短片拆解.md)<br>封面、標題、片尾的研究：[品牌資料夾的研究_封面標題片尾.md](../../brands/桑尼資料科學/研究_封面標題片尾.md)<br>聲音規格：[recipes/錄音室級旁白.md](../../recipes/錄音室級旁白.md) |
| 範例 | `/home/sunny/Videos/黃仁勳辭任/edit/short_v6.mp4`（Linux）（EP.01），分鏡寫在同一層的 `短片.json`；封面範例 `examples/cover_example_ai.png`；EP.01 比較三種封面的程式 `examples/ep01_covers.py` |
| 狀態 | 第一版 2026-11-20；2026-11-22 拆出流程和品牌，這份只留畫面規則 |

## 固定的規則

### 版面

以 1080×1920 為準，數值從參考短片量測後放大 2.25 倍，寫在 `style.json`。

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

### 配色與字體

顏色和字體都來自品牌（[BRAND.md](../../brands/桑尼資料科學/BRAND.md)），這個風格只用品牌色：

| 用途 | 色彩 |
|---|---|
| 字幕、重點字 | 薄荷綠 `#7EEBD9`（Logo 色） |
| 標籤、線條、轉場 | 紅色 `#BA4D43`（Featured Red） |
| 主色、系列條 | 青綠 `#2C918C` |
| 底色 | `#050505`、`#0F2D2B` |

參考短片原本用黃色字幕，這裡改成薄荷綠。

### 畫面質感

- **調色**：對比 1.07、飽和 0.86，暗部偏冷、亮部偏暖。
- **整體**：最後加暗角和細顆粒。
- **推近**：旁白段的畫面緩慢推近 4%；原聲段不推近，避免干擾講者。

### 節奏與轉場

| 項目 | 規則 |
|---|---|
| 旁白語速 | 對齊參考短片：含停頓約 5.6–6.0 音節/秒，停頓中位數 0.4 秒（`prosody.py --profile news`） |
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

1. 上傳兩張參考圖：真實人物照片和品牌的 `logo/logo_main_1x1.png`。上傳時要帶 `User-Agent: curl/...`，不然會被 Cloudflare 擋（錯誤碼 1010）。
2. 用下方的提示詞。範例成品：`examples/cover_example_ai.png`。
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

### 片尾和口播收尾

用品牌的直式片尾（3 秒）和固定的口播收尾，規則見 [BRAND.md](../../brands/桑尼資料科學/BRAND.md)。

## 預設值

| 項目 | 預設值 |
|---|---|
| 旁白聲音 | 品牌的 A1 男聲或 B1 女聲（見 BRAND.md） |
| 配音後製 | [錄音室級旁白](../../recipes/錄音室級旁白.md)：−16 LUFS、換氣比人聲低 24–30 dB、底噪 ≤ −65 dBFS |
| 配樂 | `assets/music_bed_news.mp3`。開場比人聲低約 20 dB，最後 25 秒逐漸升起 |
| 片中固定標題 | 封面大字縮成一行，例如「一段私事，怎麼變成\|國安疑雲」（`\|` 之後是要上重點色的字） |
| YouTube 片名 | `{說明句，不加問號}：{事件＋關鍵事實}｜科技大事 2 分鐘 #Shorts`。重要字放在前 40 字內；不用問號、不用「震驚」這類字眼 |
