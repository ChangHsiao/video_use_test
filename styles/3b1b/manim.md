# 3b1b 風格：Manim 的設定

| 項目 | 內容 |
|---|---|
| 適用範圍 | 用 Manim 做 3b1b 風格的說明動畫時讀。規則本身在 [STYLE.md](STYLE.md)，這份只講怎麼在 Manim 裡做到 |
| 相關文件 | 引擎的用法：`skills/manim-video/SKILL.md` 和它的 `references/`；範例場景：`example_scene.py` |
| 狀態 | 第一版，2026-11-20。範例場景用 Manim Community Edition 0.22.1 在 Windows 算繪過（只用 `Text`，沒有測 LaTeX） |

## 用哪一個 Manim

3Blue1Brown 自己用的是 manimgl（`3b1b/manim`），這個專案用的是 Manim Community Edition（`skills/manim-video/`）。兩個的寫法不同，**不要把 3b1b/videos 的程式貼過來跑**：寫法不相容，授權（CC BY-NC-SA）也不允許直接拿去用。照 STYLE.md 的規則，用 Community Edition 自己寫。

## 和 manim-video 的預設值不一樣的地方

用這個風格時，下面幾項以這份為準，蓋過 `skills/manim-video/SKILL.md` 的「Creative Direction」：

| 項目 | manim-video 的預設 | 3b1b 風格 |
|---|---|---|
| 底色 | `#1C1C1C` | `#000000` |
| 字型 | 全部用等寬字 | 襯線體（Noto Serif TC）；等寬字只給位元、程式碼 |
| 每個場景的主色 | 每個場景換一個 | 顏色跟著概念，整支片固定 |
| 進場動作 | 每個場景換不同的 | 照 STYLE.md「動畫」那張表，看關係決定 |
| 場景結尾 | 全部淡出 | 停在最後的重點上，不淡出 |
| 字級 | 標題 48、內文 30 | 橫式：標題 72、內文 48、標籤 30–36；直式（畫面寬 8）：44／32／24／18 |
| 字幕 | 每個動作加 `add_subcaption` | 不加；字幕由 `compose.py` 疊 |

其他（管線、檔案結構、LaTeX 注意事項、疑難排解）照 manim-video。

## 設定

直式 1080×1920，貼在場景檔最前面（`example_scene.py` 開頭那一段可以整段複製）：

```python
from manim import *

config.pixel_width, config.pixel_height = 1080, 1920
config.frame_width = 8.0
config.frame_height = 8.0 * 1920 / 1080
config.frame_rate = 30
config.background_color = "#000000"
```

橫式 16:9 時不用改畫面大小（預設高 8、寬 14.22），只設底色和格數，字級用橫式那一組。

算繪：

```bash
manim -ql  場景檔.py 場景名稱      # 草稿
manim -qh  場景檔.py 場景名稱      # 正式（解析度照上面的 config，-q 只影響沒寫在 config 的項目）
manim -s   場景檔.py 場景名稱      # 只出最後一格，用來檢查構圖
```

Windows 的路徑太長時算繪會失敗（找不到 `partial_movie_files` 底下的檔案）：加 `--media_dir` 指到短一點的資料夾。

**飽和度**：原始設定是成片飽和度 1.5 倍。Manim 算繪完，放進 `合成.json` 之前做一次：

```bash
ffmpeg -i 動畫.mp4 -vf "eq=saturation=1.5" -c:v libx264 -crf 16 -pix_fmt yuv420p 動畫_sat.mp4
```

## 風格的動作怎麼寫

| STYLE.md 的動作 | Community Edition 的寫法 |
|---|---|
| 淡入帶位移 | `FadeIn(m, shift=0.3 * UP)` |
| 描字 | `Write(text)`；長的加 `run_time=2` |
| 畫線、畫框 | `Create(line)` |
| 複製一份變過去 | `TransformFromCopy(source, result)` |
| 沿弧線變形 | `ReplacementTransform(a, b, path_arc=45 * DEGREES)` |
| 公式改寫 | `TransformMatchingTex(old, new, path_arc=45 * DEGREES)`；純文字用 `TransformMatchingShapes` |
| 依序錯開 | `LaggedStart(*anims, lag_ratio=0.25)`；同一種動作套一整組用 `LaggedStartMap(FadeIn, group, lag_ratio=0.1)` |
| 黃色細框 | `SurroundingRectangle(m, color="#FFFF00", stroke_width=2, buff=0.1)` |
| 框移到下一項 | `frame.animate.become(SurroundingRectangle(next_item, ...))` |
| 其他的調暗再恢復 | `others.save_state()` → `others.animate.set_opacity(0.35)` → `Restore(others)` |
| 沿外框掃一圈光 | `Circumscribe(m, color="#FFFF00", time_width=1.5, run_time=2)` |
| 顏色閃一下再回來 | `m.animate(rate_func=there_and_back).set_color("#FFFF00")` |
| 大括號加說明 | `Brace(m, DOWN)`，說明用 `Text` 放在 `brace.get_tip()` 旁邊（`BraceLabel` 需要 LaTeX） |
| 彎的箭頭 | `CurvedArrow(start, end, angle=-TAU / 4)` |
| 壓在圖上的字加黑描邊 | `text.set_stroke(BLACK, width=5, background=True)` |
| 用數值帶動整張圖 | `t = ValueTracker(0)`，圖形用 `always_redraw(lambda: ...)`，再 `self.play(t.animate.set_value(1), run_time=4)` |
| 發光的點 | `Dot(radius=0.08)` 外面疊 2–3 個放大、不透明度 0.1–0.3 的同色 `Dot` |
| 等速 | `rate_func=linear`；其他不用寫，預設就是平滑曲線 |
| 局部放大 | 場景繼承 `MovingCameraScene`：`self.camera.frame.save_state()` → `self.camera.frame.animate.scale(0.5).move_to(m)` → `Restore(self.camera.frame)` |
| 立體鏡頭 | 場景繼承 `ThreeDScene`：`self.move_camera(phi=70 * DEGREES, theta=-45 * DEGREES, run_time=4)`、`self.begin_ambient_camera_rotation(rate=0.03)`，要做下一個動作前 `self.stop_ambient_camera_rotation()` |
| 固定在畫面上的公式（立體場景） | `self.add_fixed_in_frame_mobjects(eq)` |

## 容易錯的地方

- `set_opacity` 會連填色一起改。箭頭、曲線這種沒有填色的東西要調暗，用 `set_stroke(opacity=...)`，不然會變成一塊色塊。調暗後要恢復的東西，先 `save_state()` 再用 `Restore`，不要用 `set_opacity(1)`（半透明的填色會被改成不透明）。
- `DecimalNumber`、`MathTex`、`Tex`、`BraceLabel`、座標軸的數字都需要 LaTeX。機器沒裝 LaTeX 時，數字用 `Text(f"{x:.2f}")`，座標軸加 `axis_config={"include_numbers": False}`。
- 字型名稱寫錯不會報錯，會默默換成別的字型。算繪後看一格，確認中文是襯線體。
- 3b1b/videos 裡常見的名稱在 Community Edition 不存在或意思不同：`ShowCreation` 是 `Create`；`Tex` 在那邊是數學式（這邊是 `MathTex`）、`TexText` 在這邊是 `Tex`；`InteractiveScene` 用 `Scene`；`self.frame.reorient(...)` 用上表的鏡頭寫法；`FlashAround` 用 `Circumscribe`；`set_backstroke` 用 `set_stroke(..., background=True)`；`GlowDot` 沒有，照上表疊。
- 一個場景一個類別、只講一個想法。不要在場景結尾加 `FadeOut(Group(*self.mobjects))`。
