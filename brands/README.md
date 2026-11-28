# 品牌層（brands/）

| 項目 | 內容 |
|---|---|
| 適用範圍 | 說明品牌資料夾放什麼、風格怎麼接上品牌、怎麼加新品牌。給 Agent 和維護的人讀 |
| 相關文件 | 整體分層：[ARCHITECTURE.md](../ARCHITECTURE.md)；風格層：[styles/README.md](../styles/README.md)；讀取程式：`helpers/registry.py` |
| 狀態 | 2026-11-22 |

## 品牌和風格的差別

| | 風格（`styles/`） | 品牌（`brands/`） |
|---|---|---|
| 管什麼 | 一種片怎麼排版、怎麼動、什麼節奏 | 這個頻道是誰：顏色、字型、logo、片尾、口播收尾、聲音 |
| 換了會怎樣 | 同一個品牌可以有好幾種風格（新聞短片、科普長片…） | 同一個風格換品牌，就是同樣的排版換一套 CIS |
| 必要嗎 | 每支片都要選一個 | 選填；沒有品牌的風格（暗色科技風、3b1b）自己定顏色 |

風格在 `style.json` 寫 `"brand": "<品牌名稱>"` 接上品牌。接上之後：

- **顏色**：品牌的 `colors` 先載入，風格自己的 `colors` 同名時蓋過去。風格的其他欄位可以直接用品牌的顏色名稱。
- **素材**：程式找檔案的順序是「影片資料夾 → 風格資料夾 → 品牌資料夾」，單集可以放自己的 logo、字型蓋過品牌的。

## 一個品牌資料夾放什麼

資料夾名稱就是品牌名稱。

| 檔案 | 必要 | 內容 |
|---|---|---|
| `brand.json` | 必要 | 給程式讀：名稱、標語、顏色、字型候選路徑、logo、片尾、口播收尾、聲音 |
| `BRAND.md` | 必要 | 給 Agent 讀：每集都要遵守的品牌規則（片尾、口播收尾、聲音） |
| `guideline/` | 選用 | 完整的 CIS 文件 |
| `logo/`、`fonts/`、`assets/` | 選用 | 品牌素材 |

### `brand.json` 的欄位

| 欄位 | 意思 |
|---|---|
| `name`、`name_en`、`tagline`、`slogan` | 品牌名稱、英文名稱（片尾用，畫面上轉成大寫）、標語（靜態片尾卡用）、口號（動畫片尾用） |
| `colors` | 顏色名稱 → `#rrggbb` |
| `fonts` | `zh`、`en` 各一串候選路徑，相對路徑從品牌資料夾（或影片資料夾）找，也可以寫系統字型的絕對路徑；用第一個存在的 |
| `logo` | `tile`（方形 logo）、`mark`（向量標誌） |
| `outro` | 片尾影片 |
| `outro_a`（選填） | 片尾 A（數據流）的文字：`slogan`（沒寫就用 `slogan`）、`footer`（最下面一行小字）。`helpers/outro_props.py` 讀它產生 Remotion 的 `--props`，片尾程式裡不寫任何文字 |
| `signoff` | 口播收尾：音檔、念的文字、字幕中英文，`voice` 是用哪個聲音（`voices` 的鍵） |
| `voices` | 旁白聲音的 ElevenLabs voice id |
| `voice_dna`（選填） | 聲音 → DNA 檔：`{"male": "assets/voice_dna/A1_男聲.json"}`。DNA 由 `helpers/voice_dna.py build` 從這個聲音的所有口播收尾量出來，新錄的音檔用 `check` 比對 |
| `series`（選填） | 系列 → 這個系列自己的 `name`、`slogan`、`outro`、`outro_a`、`signoff`（欄位和品牌層一樣）。素材依系列放在 `assets/<系列名稱>/` |
| `mascot`（選填） | 品牌角色：顏色、幾何（`geometry`）、表情清單、表情包資料夾、規範文件。所有畫角色的程式（`helpers/mascot.py`、`helpers/mascot_track.py`、`templates/manim/sun_mascot.py`）都只讀這一份 |

## 目前有的品牌

| 品牌 | 用在哪些風格 |
|---|---|
| [桑尼資料科學](桑尼資料科學/BRAND.md) | 桑尼新聞短片 |

## 怎麼加一個新品牌

1. 新增 `brands/<名稱>/`，放 `brand.json`、`BRAND.md` 和素材。
2. 要用這個品牌的風格，在 `style.json` 加 `"brand": "<名稱>"`。
3. 跑 `uv run --project . python -m unittest tests.test_registry`，它會載入每個品牌和風格，檢查素材都找得到。
