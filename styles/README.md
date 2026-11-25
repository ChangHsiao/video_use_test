# 風格層（styles/）

| 項目 | 內容 |
|---|---|
| 適用範圍 | 說明 `styles/` 怎麼分層、一個風格資料夾要放什麼、怎麼換風格、怎麼加新風格。給 Agent 和維護的人讀 |
| 相關文件 | 整體分層：[ARCHITECTURE.md](../ARCHITECTURE.md)；品牌：[brands/README.md](../brands/README.md)；製作流程：[sop/README.md](../sop/README.md)；讀取程式：`helpers/registry.py`；動畫零件庫：[templates/remotion/README.md](../templates/remotion/README.md)；Manim：`skills/manim-video/SKILL.md` |
| 狀態 | 第一版 2026-11-20；2026-11-22 加上版型（layout）和品牌（brand） |

## 這一層管什麼

一支片＝產品線（`sop/`）× 風格（這裡）× 品牌（`brands/`，選填），分層見 [ARCHITECTURE.md](../ARCHITECTURE.md)。

規則只有一條：**樣子的數值只能寫在風格或品牌資料夾裡**。合成程式、零件庫、流程文件都不寫死顏色和字級，只讀風格。內容的規矩（每句要有出處、說明動畫要標「示意圖」）屬於流程層，不管選哪種風格都要遵守。

每個風格用 `style.json` 的 `"layout"` 指定**版型**（畫面怎麼排），每個版型由一支合成程式畫：

| 版型 | 合成程式 | 畫面 |
|---|---|---|
| `broll_top`（沒寫 layout 時的預設） | `helpers/compose.py` | B-roll 放上方、模糊背景、頂部標題、數字卡、段落標題卡、雙語字幕 |
| `broll_wide` | `helpers/compose.py` | 橫式版的 `broll_top`：畫面尺寸由風格決定（長影片 1920×1080），直式素材置中、左右補模糊背景 |
| `news_band` | `helpers/news_short.py` | 模糊底加主畫面帶、資訊卡、原聲卡、雙語字幕、調色、溶接、封面和片尾 |

## 目前有的風格

| 風格 | 適合 | 合成工具 | 說明 |
|---|---|---|---|
| [暗色科技風](暗色科技風/STYLE.md) | 科普短片（預設） | `compose.py` | 暗色漸層底、紅色重點字、黃色字幕 |
| [3b1b](3b1b/STYLE.md) | 講原理、數學、演算法、AI 的解說片 | `compose.py`；動畫用 Manim 或 Remotion | 從 3Blue1Brown 的影片原始碼整理出來的畫面語言：全黑底、一個概念一個顏色、圖形從上一個圖形長出來 |
| [暗色科技風_橫式](暗色科技風_橫式/STYLE.md) | 橫式長影片（暫定） | `compose.py`（版型 `broll_wide`） | 暗色科技風的橫式版，位置和字級是暫定值 |
| [桑尼新聞短片](桑尼新聞短片/STYLE.md) | 新聞解說短片（`sop/新聞短片.md` 的預設） | `news_short.py`（版型 `news_band`） | 參考短片的版面、品牌桑尼資料科學、封面系統 C |

## 一個風格資料夾放什麼

資料夾名稱就是風格名稱。

| 檔案 | 必要 | 給誰讀 | 內容 |
|---|---|---|---|
| `STYLE.md` | 必要 | Agent | 三段：「固定的規則」（照做）、「預設值」（整理進企劃給使用者確認）、「範例」 |
| `style.json` | 必要 | 合成程式（透過 `registry.py`） | `layout`（版型）、`brand`（品牌，選填）和那個版型要的顏色、字級、位置。欄位見下面 |
| `theme.ts` | 選用 | Remotion 零件庫 | 蓋過 `edit/animations/src/theme.ts`。欄位要和 `templates/remotion/src/theme.ts` 一樣，零件才能直接用 |
| `manim.md`、範例場景 | 選用 | 用 Manim 做動畫的 Agent | 這個風格在 Manim 的設定；和 `skills/manim-video/SKILL.md` 的預設值不一樣的地方，以風格為準 |
| `assets/`、`examples/` | 選用 | — | 這個風格專用的素材（例如配樂）和範例。品牌共用的素材（logo、片尾）放品牌資料夾；工具放 `helpers/` |

`合成.json` 的 `"style"` 只能指到 `broll_top`、`broll_wide` 的風格；指到其他版型時 `compose.py` 會報錯，告訴你該用哪支程式。

### `broll_top` 版型的欄位（`compose.py` 讀的）

座標以 1080×1920 為準，`y` 是文字中心離頂部的距離。

```json
{
  "colors": {"red": "#ff5a3c", "white": "#ffffff", "line": "#c9d1db"},
  "number_colors": ["red", "white"],
  "broll": {"top": 560, "bg_zoom": 1.15, "bg_dim": 0.45},
  "title": {"size": 52, "y": 120, "color": "white", "accent": "red"},
  "number": {
    "big": {"size": 120, "y": 1300, "color": "white"},
    "label": {"size": 42, "y": 1405, "color": "line"},
    "note": {"size": 30, "y": 1465, "color": "line"}
  },
  "section": {
    "background": ["#1c2129", "#0b0d10"],
    "text": {
      "small": {"size": 40, "y": 850, "color": "line"},
      "big": {"size": 110, "y": 960, "color": "red"}
    }
  },
  "subtitle": {
    "zh": {"size": 58, "y": 1640, "color": "white"},
    "en": {"size": 36, "y": 1712, "color": "white"}
  }
}
```

| 欄位 | 意思 |
|---|---|
| `colors` | 顏色名稱 → `#rrggbb`。其他欄位的 `color` 只能寫這裡有的名稱 |
| `number_colors` | `合成.json` 的數字卡 `color` 可以用哪些顏色名稱 |
| `broll` | 橫式 B-roll 的版面：`top` 原畫面離頂部多遠；背景是同一個畫面放大 `bg_zoom` 倍、模糊、亮度調到 `bg_dim` |
| `title` | 頂部標題；`accent` 是重點字的顏色 |
| `number` | 數字卡三行：大數字（沒指定顏色時用 `big.color`）、說明、估算小字 |
| `section` | 段落標題卡：`background` 是由中間往外的兩個顏色（寫一樣就是單色）；`text` 是小標、大標 |
| `subtitle` | 字幕：`zh` 第一語言、`en` 第二語言 |
| `brand`（選填） | 掛哪個品牌（`brands/` 的資料夾名稱）。品牌的顏色會併進 `colors`，同名時風格優先 |
| `logo`（選填） | 品牌 logo 的中心位置 `x`、`y` 和邊長 `size`（1080×1920 座標），可加 `opacity`；圖檔是品牌 `brand.json` 的 `logo.tile`。畫在標題、字幕下面 |
| `mascot`（選填） | 品牌角色的家（起點）：中心位置 `x`、`y` 和顯示大小 `size`；`lane` 是角色走道 `{"x": [x0, x1], "y": [y0, y1]}`，角色的中心只能在這個範圍裡移動（要避開說明動畫），沒寫就不限制。`helpers/compose.py` 每格即時畫角色，疊在畫面上、文字下面，字幕永遠在最上層；`合成.json` 寫了 `mascot` 才畫 |

缺欄位、顏色寫錯、用到 `colors` 沒有的名稱，`registry.py` 載入時就報錯，不會合成到一半才壞。

### `broll_wide` 版型的欄位（`compose.py` 讀的）

範例是 [暗色科技風_橫式/style.json](暗色科技風_橫式/style.json)。欄位和 `broll_top` 一樣，差在：

| 欄位 | 意思 |
|---|---|
| `canvas` | 畫面寬高 `{"w", "h"}`，其他欄位的座標都以它為準 |
| `text_max_w` | 一行最寬多少，超過就縮小字級（`broll_top` 固定 1000） |
| `broll` | 只要 `bg_zoom`、`bg_dim`：直式素材置中，左右用同一個畫面放大、模糊、調暗補滿；不需要 `top` |
| `logo`、`mascot` | 還不支援，寫了就報錯 |

### `news_band` 版型的欄位（`news_short.py` 讀的）

範例是 [桑尼新聞短片/style.json](桑尼新聞短片/style.json)。顏色名稱可以用品牌的（`mint`、`red`…），風格自己的 `colors` 同名時蓋過品牌。

| 欄位 | 意思 |
|---|---|
| `canvas` | 畫面寬高、每秒格數 |
| `band` | 主畫面帶的 `y`、高度 `h`、下緣漸層 `fade`；`ticker_trim` 是新聞台畫面下方裁掉的比例 |
| `title` | 固定標題的字級、位置、顏色、重點色 |
| `info`、`sot_card`、`credit` | 資訊卡、原聲卡、畫面出處的位置和字級；`tag_bg` 是標籤底色 |
| `subtitle` | 中英字幕的字級、位置、顏色；`min_size` 是太長時最小縮到多少 |
| `grade` | 調色（對比、飽和、gamma、色彩平衡）、推近比例、暗角、顆粒 |
| `transitions` | 段內溶接、段間溶接、原聲前後留白、段尾留白（秒） |
| `news_sources` | 檔名含這些字的來源，預設裁掉下方跑馬燈 |
| `cover`、`outro`、`voice`、`music` | 封面、靜態片尾長度、配音、配樂的設定 |

## 怎麼換風格

1. **企劃**（流程的確認點 2）的「風格」寫風格名稱。沒指定時用該 SOP 的預設（科普短片是「暗色科技風」，新聞短片是「桑尼新聞短片」）。
2. Agent 讀 `styles/<風格名稱>/STYLE.md`，做畫面、動畫、字幕時照它的「固定的規則」。
3. **合成**：`broll_top` 的風格在 `合成.json` 加一行 `"style": "<風格名稱>"`（沒寫就是「暗色科技風」，舊的 `合成.json` 不用改）；`news_band` 的風格在 `news_short.py` 加 `--style <風格名稱>`。
4. **Remotion 動畫**：把 `templates/remotion/` 複製成 `edit/animations/` 之後，風格有 `theme.ts` 的話，用它蓋過 `edit/animations/src/theme.ts`。
5. **Manim 動畫**：照風格的 `manim.md`。

同一支片要比較兩種風格時，只改 `合成.json` 的 `"style"` 再跑一次 `compose.py --samples`，就能拿到兩組樣張；動畫要換風格則要換 `theme.ts` 重新算繪。

## 怎麼加一個新風格

1. 新增 `styles/<名稱>/`，從最接近的風格複製 `STYLE.md` 和 `style.json` 來改。
2. `style.json` 寫上 `layout`（要接品牌就寫 `brand`），改完跑一次：`uv run --project . python -m unittest tests.test_registry`，它會把每個風格、品牌載入一遍，檢查欄位和素材。
3. 在上面「目前有的風格」表加一行。
4. 風格需要合成程式還不會畫的東西時（例如新的卡片種類），先改那支程式讓它讀 `style.json` 的新欄位，並在 `registry.py` 該版型的檢查函式加上這個欄位；不要在程式裡為某一個風格寫特例。
5. 需要全新的畫面排法時，寫一支新的合成程式，在 `registry.py` 用 `@register_layout("<版型名稱>")` 登記它的欄位檢查。
