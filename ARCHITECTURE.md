# 架構

| 項目 | 內容 |
|---|---|
| 適用範圍 | 這個 repo 怎麼分層、每個資料夾管什麼、彼此怎麼接、要加新東西時放哪裡。給維護的人和 Agent 讀 |
| 相關文件 | Agent 的入口：[SKILL.md](SKILL.md)；各層的細節：[sop/README.md](sop/README.md)、[recipes/README.md](recipes/README.md)、[styles/README.md](styles/README.md)、[brands/README.md](brands/README.md) |
| 狀態 | 2026-11-22 重構後的版本 |

## 一支片由三個獨立的面向組成

```
一支片 ＝ 產品線（類型 × 格式） × 風格（視覺語言） × 品牌（選填）
          科普短片、新聞短片         暗色科技風、3b1b      桑尼資料科學
          （未來）科普長片、長片拆短片   桑尼新聞短片
```

三個面向分開放，才能各自抽換：同一個品牌可以套在長片和短片上，同一個風格可以拿來做不同類型的片，換風格不用改流程。

## 分層

```
              README.md（給人）              SKILL.md（給 Agent：硬規則＋路由）
                     │                               │
 ┌───────────────────┴───────────────────────────────┴──────────────────────┐
 │ 流程層  sop/       產品線：步驟、確認點、交付物（照做）                      │
 │         recipes/   經驗：某種素材或手法怎麼處理、踩過的坑（預設要先問）       │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ 外觀層  styles/    視覺語言：STYLE.md（規則）＋ style.json（版面數值）        │
 │         brands/    品牌：顏色、字型、logo、片尾、口播收尾（長短片共用）        │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ 引擎層  helpers/             Python 工具：取得素材、轉錄、剪接、配音、合成     │
 │         templates/remotion/  說明動畫的零件庫（React）                       │
 │         skills/manim-video/  Manim 動畫引擎（外部引入）                      │
 │         templates/manim/     Manim 共用元件（品牌角色 sun_mascot.py）        │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ 驗證    tests/     每一層的契約都有測試                                      │
 └──────────────────────────────────────────────────────────────────────────┘
    產出一律寫在 repo 外面：<影片資料夾>/edit/
```

**依賴只往下走。** 流程說「用哪個風格」，不寫顏色；風格寫數值，不寫程式；引擎讀數值，不知道是哪個流程、哪個品牌在用它。

| 層 | 資料夾 | 可以引用 | 不可以 |
|---|---|---|---|
| 流程 | `sop/`、`recipes/` | 風格、品牌、引擎的用法 | 寫死顏色、字級、座標 |
| 外觀 | `styles/`、`brands/` | 自己的素材；風格可以指定一個品牌 | 放程式（範例除外，放 `examples/`） |
| 引擎 | `helpers/`、`templates/`、`skills/` | `registry.py` 讀到的風格和品牌 | 寫死某個風格或品牌的值；寫死電腦上的絕對路徑 |

## 設計模式對照

| 模式 | 在哪裡 | 解決什麼 |
|---|---|---|
| **登記處（Registry）＋外掛** | `helpers/registry.py`：`styles/`、`brands/` 照資料夾自動發現；版型用 `@register_layout` 登記 | 加一個風格或品牌只要放一個資料夾，不改程式（熱插拔） |
| **策略（Strategy）** | 版型（layout）：`broll_top`、`broll_wide`（橫式）由 `compose.py` 畫，`news_band` 由 `news_short.py` 畫；每個版型有自己的欄位檢查 | 不同的畫面排法各自一套，風格只要說用哪一個 |
| **責任鏈（Chain of Responsibility）** | `Style.asset()`：影片資料夾 → 風格資料夾 → 品牌資料夾，第一個找到的生效 | 單集可以蓋過風格，風格可以蓋過品牌，不用複製整份素材 |
| **值物件（Value Object）** | `registry.Style`、`registry.Brand`（不可變的 dataclass） | 風格讀進來之後不會被半路改掉；顏色已經合併好（品牌的顏色加上風格自己的） |
| **相同的管線階段** | 兩個合成程式都是：讀分鏡 → 算時間軸 → 底層畫面 → 疊加層 → 混音 → 輸出 | 新版型照同樣的階段寫，檢查點（樣張、樣片）對得上 |

兩個合成程式沒有硬合成一個類別：它們的分鏡格式不同（`合成.json` 用字幕文字對位、`短片.json` 用配音逐句時間和原聲區塊），硬合會讓兩邊的舊分鏡檔都失效。共用的是**契約**：同一個 `registry.py`、同一套 `style.json` 規則、同一種素材查找順序。

## 階段之間的交接檔（`<影片資料夾>/edit/`）

| 檔案 | 誰寫 | 誰讀 |
|---|---|---|
| `transcripts/*.json` | `transcribe.py`、`fetch_youtube.py` | `pack_transcripts.py`、`render.py` |
| `takes_packed.md` | `pack_transcripts.py` | Agent（寫內容目錄、稿子） |
| `企劃.md`、`稿子.md`、`分鏡表.md` | Agent | 使用者確認；Agent 寫分鏡檔 |
| `voice_lines.json`、`cues.json`、`master.srt` | `align_voice.py` 或 `voice_tts.py` | `compose.py`、Remotion 零件庫 |
| `voice/錄音室版/<tag>.json` | `prosody.py` | `news_short.py` |
| `合成.json` | Agent | `compose.py`、`mascot_track.py`、`mascot_qa.py`（讀 `mascot.events`） |
| `mascot_qa/report.md`＋截圖 | `mascot_qa.py` | 使用者、Agent（出預覽前要全部 PASS） |
| `mascot/voice_features.npz` | `compose.py`、`mascot_track.py`（配音的音量、音高，依音檔修改時間自動重算） | 同左（角色的嘴型、起伏） |
| `mascot/track.mov` | `mascot_track.py`（固定大小的角色軌，給其他流程） | 其他流程；`compose.py` 已改成每格即時畫角色 |
| `短片.json` | Agent | `news_short.py` |
| `edl.json` | Agent | `render.py`、`export_xml.py` |
| `project.md` | Agent | 下一次工作階段的 Agent |

交接檔的格式固定之後，「長片拆短片」可以直接讀長片的稿子、配音和分鏡，不用重做研究和配音。

## 長片和短片

| | 短片（9:16） | 長片（16:9） |
|---|---|---|
| 產品線 | `sop/科普短片.md`、`sop/新聞短片.md` | 還沒寫（`sop/科普長片.md`） |
| 版型 | `broll_top`、`news_band` | `broll_wide`（風格：暗色科技風_橫式，位置暫定） |
| 共用 | 研究、出處規則、配音工具、品牌、動畫零件、品質檢查 | 同左 |

一個風格要同時支援長片和短片時，`style.json` 會分成兩段版面；品牌不用改。目前長片用另一個風格（暗色科技風_橫式），還沒做成兩段。

## 要加新東西時放哪裡

| 要加的 | 放哪裡 | 要做什麼 |
|---|---|---|
| 一種新的畫面風格 | `styles/<名稱>/` | `STYLE.md`＋`style.json`（寫 `layout`），跑 `tests.test_registry` |
| 一個新品牌 | `brands/<名稱>/` | `brand.json`＋素材，風格的 `style.json` 寫 `"brand": "<名稱>"` |
| 一種新的畫面排法 | `helpers/` | 寫合成程式，在 `registry.py` 用 `@register_layout` 登記欄位檢查 |
| 一種新的片（產品線） | `sop/<名稱>.md` | 步驟、確認點、交付物；指定預設風格；在 `SKILL.md` 的 SOPs 加一行 |
| 一份做片經驗 | `recipes/<名稱>.md` | 照 `recipes/README.md` 的三種內容寫；在 `SKILL.md` 的 Recipes 加一行 |
| 一支工具 | `helpers/<名稱>.py` | 從 repo 執行，路徑用參數給（`--edit`），不複製到影片資料夾 |

## 穩定性的規則

- **工具從 repo 執行，不複製到每支片的資料夾。** 複製出去的版本會停在舊版，修了 repo 也不會跟著改。
- **程式裡不寫死電腦上的路徑。** 字型、logo 這類檔案寫在 `brand.json` 的候選清單裡，`Style.asset()` 找第一個存在的。
- **外部呼叫要會結束。** ffmpeg 不用沒有盡頭的濾鏡（例如不設長度的 `apad`），會失敗的呼叫要有重試或逾時。
- **重構要有標準答案。** 改合成程式之前先存一份舊版的輸出（時間軸、ffmpeg 指令、疊加層畫面），改完逐項比對；2026-11-22 搬移 `news_short.py` 時三項都完全相同。

## 還沒做的

- `sop/科普長片.md`；長片版型已有 `broll_wide`，位置和字級還是暫定值
- `transcribe.py` 和 `voice_tts.py` 各有一份讀 ElevenLabs 金鑰的程式，可以合成一份
- `styles/3b1b/theme.ts`、`templates/remotion/src/brands/` 沒有編譯過
