# 說明動畫零件庫（Remotion）

| 項目 | 內容 |
|---|---|
| 適用範圍 | 用 Remotion 做說明動畫：背景、標題、標註、箭頭、粒子流等零件，時間對齊字幕 |
| 相關文件 | 什麼時候用、畫面規矩：`sop/科普短片.md` 第 11 步；顏色和字級的來源：`sop/風格_暗色科技風.md`；字幕時間：`helpers/align_voice.py` |
| 狀態 | 只在 WSL 測過，Windows、Mac 沒測過 |

## 怎麼開始

在影片資料夾的 `edit/` 底下執行：

```bash
cp -r <skill 資料夾>/templates/remotion animations
cd animations
npm install
```

- 第 1 行：把零件庫複製成 `edit/animations/`。整支片的動畫都放在這一個資料夾，Remotion 只裝一次（約 700 MB）
- 第 3 行：安裝 Remotion。出現 `esbuild` 的 install-scripts 警告可以不管，實測照樣能算繪

## 零件

都從 `src/parts/` 匯入：`import {Background, Title, ...} from '../parts';`。座標以 1080×1920 設計。

| 零件 | 做什麼 | 主要設定 |
|---|---|---|
| `Background` | 暗色漸層加細格線，放在最底層，其他東西當它的 children | `grid` |
| `Title` | 灰色小標加白色大標，大標裡指定的字換強調色 | `small`、`big`、`accent`、`accentColor` |
| `DiagramBadge` | 標題下方的「示意圖」標籤。**每段說明動畫都要有** | `text` |
| `Canvas` | 鋪滿畫面的 SVG，內建發光效果 `filter="url(#glow)"`；圖形都畫在裡面 | `defs`（自己的漸層） |
| `Callout` | 小圓點、引線、文字依序出現，說明「這是什麼」 | `x,y`（被標的點）、`tx,ty`（文字位置）、`text`、`start` |
| `Arrow` | 往上下左右長出去的箭頭，可附文字，表示力、移動、流動 | `x,y`、`dir`、`len`、`start`、`text`、`bob`（長完後輕輕晃） |
| `ParticleStream` | 從一點連續噴出小點，越飛越散、越淡：氣體、水流、熱、蒸氣 | `x,y`、`dir`、`start`、`speed`、`life`、`size`、`sizeGrow`、`seed` |
| `progress`、`pop`、`drawStroke` | 淡入進度（0→1）、彈出、線條一筆畫出 | `progress(frame, 開始格, 長度)` |
| `rand`、`sec` | 固定的偽隨機（每次算繪都一樣）、秒數換格數 | |

完整的用法看 `src/examples/Boiling.tsx`。**範例只學寫法**：主題、構圖、文字都要照這支片的分鏡表重新想，不要照抄。範例讀的是 `public/example_cues.json`，要看它的畫面時，算繪不加 `--public-dir`。

## 寫一段動畫

1. 新增 `src/<名稱>.tsx`，用零件組畫面；零件庫沒有的圖形（車身、器材、人體構造）自己用 SVG 畫
2. 在 `src/Root.tsx` 登記一行 `<Composition id="<名稱>" ... durationInFrames={秒數 × 30} />`；用不到的範例那行可以刪掉
3. 顏色只用 `theme.colors` 裡的；換風格時只改 `src/theme.ts`

## 時間對齊字幕

```tsx
const at = useCueTimer('這段動畫第一句字幕的文字');
<Callout ... start={at('念到這句時標註出現')} />
```

- `at(文字)` 回傳念到那句時是這段動畫的第幾格；文字比對時會忽略空白和標點
- 找不到、或有好幾句字幕都含這段文字時，算繪會直接停下來並說明是哪段文字。文字寫長一點就能分開
- `at(文字)` 只從動畫第一句往後找，前面出現過的同一句不會被找到
- 動畫第一句在整支片出現不只一次時，算繪會停下來；照訊息加上它的前一句：`useCueTimer(['它的前一句', '第一句'])`
- 限制：短字幕會被 `align_voice.py` 合併，查到的是合併後那句的開始時間，可能比真正念到的時間早零點幾秒
- 沒有 `cues.json` 時，改用秒數：`start={sec(2.45)}`

## 算繪

在 `edit/animations/` 執行：

```bash
npx remotion still <名稱> out/<名稱>.png --frame=90 --public-dir=..
npx remotion render <名稱> out/<名稱>.mp4 --public-dir=..
```

- 第 1 行：先輸出一格截圖確認畫面。樣張（SOP 確認點 4）就用這個指令，挑動畫最完整的那一格
- 第 2 行：輸出整段影片
- `--public-dir=..` 讓程式讀到 `edit/cues.json`。配音重做時，重跑 `align_voice.py` 再算繪，動畫程式不用改
