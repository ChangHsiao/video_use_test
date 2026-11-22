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
- 錄製：`helpers/signoff.py`，用較穩定的設定：stability 0.65、speed 0.98、固定 seed。
- 定版（2026-11-20）：「這裡是桑尼資料科學，每週用數據，拆解一則科技大事。」，A1 男聲，5.0 秒，檔案 `assets/signoff.wav`。
- 收尾後**不再加**「喜歡請按讚、追蹤、訂閱、分享」的口播。理由：會讓片尾多出 2–3 秒沒有內容的時間，觀眾容易滑走，也打斷循環播放；片尾動畫已經用圖示呈現這三件事。要引導互動，就在收尾前放本集提問。
- 發片頻率如果改成每天，要重錄這一句，承諾和實際頻率必須一致。

## 聲音

| 聲音 | ElevenLabs voice id |
|---|---|
| A1 男聲 | `CG56nF519jHs9bMWKdXk` |
| B1 女聲 | `gGmJOmvg7PPQJ8AkL8Yd` |

聲音範本（`voice.json` 和換氣素材）在 `D:\videos\聲音範本\`，不在 repo 裡。後製規格見 [錄音室級旁白](../../recipes/錄音室級旁白.md)。
