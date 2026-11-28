# 品牌：桑尼資料科學

| 項目 | 內容 |
|---|---|
| 適用範圍 | 桑尼資料科學（Sunny Data Science）每一支片都要遵守的品牌規則，長片和短片共用。給 Agent 讀 |
| 給程式讀的數值 | `brand.json` |
| 完整 CIS | `guideline/`：[品牌規範](guideline/brand_guideline.md)、[色彩](guideline/color-palette.md)、[行動呼籲文案庫](guideline/cta_library.md)、[輸出規格](guideline/output_specs.md) |
| 研究 | [研究_封面標題片尾.md](研究_封面標題片尾.md) |
| 用這個品牌的風格 | [桑尼新聞短片](../../styles/桑尼新聞短片/STYLE.md) |
| 狀態 | 2026-11-20 定版；2026-11-22 從風格資料夾拆出來 |

## 顏色與字體

| 用途 | 名稱 | 色碼 |
|---|---|---|
| Logo 色、重點 | `mint` | `#7EEBD9` |
| 標籤、線條、轉場 | `red`（Featured Red） | `#BA4D43` |
| 主色、系列條 | `teal` | `#2C918C` |
| 深色底 | `bg`、`teal_dark` | `#050505`、`#0F2D2B` |
| 輔助 | `navy` | `#1E3A5F` |

字體：中文 Noto Sans TC，英文 Inter（`fonts/InterVariable.ttf`）。不使用 CIS 以外的顏色。

## 片尾（A 數據流）

- 直式 3 秒：`assets/outro_A_3s.mp4`（另有 4 秒版 `assets/outro_A_4s.mp4`），由最後一個鏡頭溶接進來。
- 動畫內容：Logo 線條自己描繪、填色、點亮眼睛；品牌名稱出現，英文字距展開；口號「用數據，看懂科技大事。」；追蹤、按讚、分享三個線條圖示依序畫出；最後是「每週拆解一則科技大事」。
- 原始碼：`templates/remotion/src/brands/桑尼資料科學/outro/`。要改文字或長度時，把這個資料夾複製進 Remotion 專案的 `src/outro/`，在 Root 註冊 `O1`（4 秒），以及 `<O1 speed={4/3} />`（3 秒）。
- 研究結論：Shorts 的片尾要短。重播也算觀看次數，片尾太長，觀眾會在片尾滑走。不要只喊「記得訂閱」，要說觀眾能得到什麼。

## 口播收尾（聲音標誌）

- 每集最後一句旁白是固定的收尾口號，**一次錄好、每集都用同一個檔案**，不能每集重新生成。理由：每次生成的語氣都不一樣，就形不成記憶點。
- 定版（2026-11-22）：「這裡是 Sunny 資料科學，每週用數據，拆解一則科技大事。」採用黃仁勳辭任專案選定的 `C_warm_raw.mp3`，A1 男聲，約 5.44 秒。
- 剪輯時由 `brand.json` 的 `signoff.audio` 取得 [48 kHz／24-bit 單聲道乾聲 WAV](assets/signoff_sunny_podcast.wav)。[核准原檔 MP3](assets/signoff_sunny_podcast_source.mp3) 原樣保存，WAV 只做解碼與取樣率轉換。字幕沿用品牌寫法「桑尼資料科學」。
- 口吻以台灣華語的清楚咬字為底，帶淡法式語調、柔和的 Podcast 收尾和一點俏皮感。把「這裡是 Sunny 資料科學」連成一句，Sunny 有輕重音，尾音順勢接進「資料科學」。後半句延續同一種音色和語氣。
- 收尾後**不再加**「喜歡請按讚、追蹤、訂閱、分享」的口播。理由：會讓片尾多出 2–3 秒沒有內容的時間，觀眾容易滑走，也打斷循環播放；片尾動畫已經用圖示呈現這三件事。要引導互動，就在收尾前放本集提問。
- 發片頻率如果改成每天，要重錄這一句，承諾和實際頻率必須一致。

### 定版紀錄

- 初次把手機錄音接在旁白後，音色和底噪的落差太明顯。手機檔可用來參考停頓與重音；固定片尾使用 A1 的乾淨聲線。
- A 美式與 C 法式的單字拼接保留了俏皮感，兩端的音高及咬字轉換仍突兀。整句法式試稿曾重念開頭；用音高和速度拉出語氣的版本又出現機械感。定版改用 ElevenLabs 整句連讀，由使用者在連續試聽後選定 `C_warm_raw.mp3`。
- 需要更換口號時，用現有 A1 聲線整句試錄，以同等音量接在正片最後一句後比較。逐字核對有沒有重複或漏字，並聽「是 → Sunny → 資料科學」的銜接。定版後沿用同一份乾聲，配樂與片尾混音在各集處理。

## 系列：經典乾貨拆解

講原理的科普片（3b1b 風格）。設定在 `brand.json` 的 `series.explainer`，和新聞短片分開：

| 項目 | 經典乾貨拆解 | 新聞短片（對照） |
|---|---|---|
| 口號 | 帶你深入淺出，搞懂每一個為什麼。 | 用數據，看懂科技大事。 |
| 片尾（吉祥物版，5 秒） | `assets/outro_explainer.mp4`：太陽吉祥物、logo、口號、三個按鈕。原始碼 `templates/manim/outro_explainer.py` | — |
| 片尾（A 數據流版，3 秒） | `assets/outro_explainer_A_3s.mp4`：主口號「用白話，理解生活科技。」，小字「帶你深入淺出，搞懂每一個為什麼」。Remotion 的 `OutroA-explainer-3s` | `assets/outro_A_3s.mp4`（`OutroA-news-3s`） |
| 口播收尾 | 「這裡是 Sunny 資料科學，帶你深入淺出，搞懂每一個為什麼。」`assets/signoff_explainer.wav`，5.44 秒 | `assets/signoff_sunny_podcast.wav` |
| 口播畫面字幕 | 這裡是桑尼資料科學　帶你深入淺出搞懂每一個為什麼 | 這裡是桑尼資料科學　每週用數據拆解一則科技大事 |
| 口播英文字幕 | Sunny Data Science: every why, made simple. | Sunny Data Science: one tech story, decoded with data, every week. |

### 口播定版紀錄（2026-11-28）

- 照新聞口播的做法：A1 男聲整句連讀，用 ElevenLabs 原始檔，不拼接、不調音高和速度。
- 試錄 7 個版本：4 個只調設定（stability 0.40–0.65、speed 0.94–0.98），3 個在句中加口吻標籤（淡法式、溫暖、Podcast）。全部用 Scribe 逐字核對，沒有重複或漏字；接在新聞口播後、對齊 −16.5 LUFS 比較。
- 使用者選定 T1：`signoff.py` 的原設定（stability 0.65、similarity 0.85、style 0.25、speed 0.98、seed 2026，模型 `eleven_v4`）。和新聞口播同一套設定，語氣最穩。
- [核准原檔 MP3](assets/signoff_explainer_source.mp3) 原樣保存；[WAV](assets/signoff_explainer.wav) 只做解碼與取樣率轉換（48 kHz／24-bit 單聲道）。

## 聲音

| 聲音 | ElevenLabs voice id |
|---|---|
| A1 男聲 | `CG56nF519jHs9bMWKdXk` |
| B1 女聲 | `gGmJOmvg7PPQJ8AkL8Yd` |

影片工作資料夾的根目錄（下稱 `<影片根目錄>`）由程式自動偵測：Windows 是 `D:\videos\`，Linux 是 `/home/sunny/Videos/`（`~/Videos`），設了環境變數 `VIDEOS_ROOT` 就以它為準（見 `helpers/paths.py`）。每一支剪輯影片都放在這底下。聲音範本（`voice.json` 和換氣素材）在 `<影片根目錄>/聲音範本/`，不在 repo 裡；`--voice-dir` 可以只寫範本名稱，例如 `A1_男聲`。後製規格見 [錄音室級旁白](../../recipes/錄音室級旁白.md)。
