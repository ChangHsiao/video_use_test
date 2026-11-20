# 風格層（styles/）

| 項目 | 內容 |
|---|---|
| 適用範圍 | 說明 `styles/` 怎麼分層、一個風格資料夾要放什麼、怎麼換風格、怎麼加新風格。給 Agent 和維護的人讀 |
| 相關文件 | 製作流程：[sop/科普短片.md](../sop/科普短片.md)；合成工具：`helpers/compose.py`；動畫零件庫：[templates/remotion/README.md](../templates/remotion/README.md)；Manim：`skills/manim-video/SKILL.md` |
| 狀態 | 第一版，2026-11-20 |

## 分層

| 層 | 放在哪裡 | 管什麼 | 換風格時會不會動 |
|---|---|---|---|
| 核心 | `SKILL.md`、`helpers/` | 剪輯的硬規則、轉錄、合成、檢查工具 | 不動 |
| 流程 | `sop/`、`recipes/` | 一種影片怎麼從素材做到成片、在哪裡停下來問使用者 | 不動 |
| **風格** | `styles/<風格名稱>/` | 看起來、聽起來的樣子：顏色、字級、位置、動畫怎麼動、節奏 | **只換這一層** |
| 動畫引擎 | `templates/remotion/`、`skills/manim-video/` | 用什麼工具把動畫畫出來 | 不動；風格提供自己的設定檔蓋過引擎的預設值 |

規則只有一條：**樣子的數值只能寫在風格資料夾裡**。`compose.py`、零件庫、流程文件都不寫死顏色和字級，只讀風格。內容的規矩（每句要有出處、說明動畫要標「示意圖」）屬於流程層，不管選哪種風格都要遵守。

## 目前有的風格

| 風格 | 適合 | 合成工具 | 說明 |
|---|---|---|---|
| [暗色科技風](暗色科技風/STYLE.md) | 科普短片（預設） | `compose.py` | 暗色漸層底、紅色重點字、黃色字幕 |
| [3b1b](3b1b/STYLE.md) | 講原理、數學、演算法、AI 的解說片 | `compose.py`；動畫用 Manim 或 Remotion | 從 3Blue1Brown 的影片原始碼整理出來的畫面語言：全黑底、一個概念一個顏色、圖形從上一個圖形長出來 |

## 一個風格資料夾放什麼

資料夾名稱就是風格名稱。

| 檔案 | 必要 | 給誰讀 | 內容 |
|---|---|---|---|
| `STYLE.md` | 必要 | Agent | 三段：「固定的規則」（照做）、「預設值」（整理進企劃給使用者確認）、「範例」 |
| `style.json` | 用 `compose.py` 合成就必要 | `compose.py` | 疊加層（頂部標題、數字卡、段落標題卡、字幕）和 B-roll 版面的顏色、字級、位置。欄位見下面 |
| `theme.ts` | 選用 | Remotion 零件庫 | 蓋過 `edit/animations/src/theme.ts`。欄位要和 `templates/remotion/src/theme.ts` 一樣，零件才能直接用 |
| `manim.md`、範例場景 | 選用 | 用 Manim 做動畫的 Agent | 這個風格在 Manim 的設定；和 `skills/manim-video/SKILL.md` 的預設值不一樣的地方，以風格為準 |
| 其他（素材、字型、工具） | 選用 | — | 這個風格專用的東西放在自己的資料夾，不放到 `helpers/` |

不用 `compose.py` 的風格（有自己的合成工具），`style.json` 的欄位可以自己訂，但 `合成.json` 的 `"style"` 不能指到它。

### `style.json` 的欄位（`compose.py` 讀的）

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

缺欄位、顏色寫錯、用到 `colors` 沒有的名稱，`compose.py` 一開始就報錯，不會合成到一半才壞。

## 怎麼換風格

1. **企劃**（流程的確認點 2）的「風格」寫風格名稱。使用者沒指定就用「暗色科技風」。
2. Agent 讀 `styles/<風格名稱>/STYLE.md`，做畫面、動畫、字幕時照它的「固定的規則」。
3. **合成**：`合成.json` 加一行 `"style": "<風格名稱>"`。沒寫就是「暗色科技風」，舊的 `合成.json` 不用改。
4. **Remotion 動畫**：把 `templates/remotion/` 複製成 `edit/animations/` 之後，風格有 `theme.ts` 的話，用它蓋過 `edit/animations/src/theme.ts`。
5. **Manim 動畫**：照風格的 `manim.md`。

同一支片要比較兩種風格時，只改 `合成.json` 的 `"style"` 再跑一次 `compose.py --samples`，就能拿到兩組樣張；動畫要換風格則要換 `theme.ts` 重新算繪。

## 怎麼加一個新風格

1. 新增 `styles/<名稱>/`，從最接近的風格複製 `STYLE.md` 和 `style.json` 來改。
2. `style.json` 改完跑一次：`uv run --project . python -m unittest tests.test_compose.StyleTest`，它會把 `styles/` 底下每個給 `compose.py` 用的風格載入一遍。
3. 在上面「目前有的風格」表加一行。
4. 風格需要 `compose.py` 還不會畫的東西時（例如新的卡片種類），先改 `compose.py` 讓它讀 `style.json` 的新欄位，不要在程式裡為某一個風格寫特例。
