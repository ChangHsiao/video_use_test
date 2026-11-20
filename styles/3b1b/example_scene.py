"""3b1b 風格的 Manim 範例場景（Manim Community Edition，直式 1080×1920）。

用法（不需要 LaTeX，只用 Text）：
    manim -ql styles/3b1b/example_scene.py AttentionExample        # 草稿影片
    manim -s  styles/3b1b/example_scene.py AttentionExample        # 只出最後一格

只學寫法：設定、色票、字級、節奏照 styles/3b1b/STYLE.md；主題和構圖每支片重新想。
檔案開頭到 hold() 為止可以整段複製到自己的場景檔。
"""

from manim import *

# ---------- 畫面設定：全黑底、30 格、直式；畫面寬 8 個單位 ----------
config.pixel_width, config.pixel_height = 1080, 1920
config.frame_width = 8.0
config.frame_height = 8.0 * 1920 / 1080
config.frame_rate = 30
config.background_color = "#000000"

# ---------- 色票：一個概念固定一個顏色，整支片不換 ----------
YELLOW_3B = "#FFFF00"  # 只表示「看這裡」
BLUE_3B = "#58C4DD"
TEAL_3B = "#5CD0B3"  # 正在作用、正在流動的東西
RED_3B = "#FC6255"  # 錯誤、被擋下來、負的值
GREEN_3B = "#83C167"  # 正確、通過
PINK_3B = "#D147BD"
GREY_A_3B, GREY_B_3B, GREY_C_3B, GREY_D_3B = "#DDDDDD", "#BBBBBB", "#888888", "#444444"

# ---------- 字：襯線體；直式畫面寬只有 8，字級用橫式的一半左右 ----------
FONT = "Noto Serif TC"  # 沒裝會自動換成系統字型，算繪後要看一格確認
TITLE, BODY, LABEL, SMALL = 44, 32, 24, 18

# ---------- 節奏 ----------
RUN = 2.0  # 一般動作
QUICK = 1.0  # 小動作
DIM = 0.35  # 不是主角的東西調暗到多少


def text(s, size=BODY, color=WHITE):
    return Text(s, font=FONT, font_size=size, color=color)


# 黃色細框：框住現在要看的東西
def look_at(mob, buff=0.1):
    return SurroundingRectangle(mob, color=YELLOW_3B, stroke_width=2, buff=buff)


class AttentionExample(Scene):
    def construct(self):
        # 直接從主角開始，不放標題卡：一排字卡依序浮上來
        words = ["貓", "坐", "在", "墊子", "上"]
        chips = VGroup()
        for w in words:
            label = text(w)
            box = Rectangle(width=label.width + 0.4, height=0.9, stroke_color=WHITE, stroke_width=1,
                            fill_color=GREY_D_3B, fill_opacity=0.5)
            chips.add(VGroup(box, label))
        chips.arrange(RIGHT, buff=0.25).shift(UP * 2)
        self.play(LaggedStart(*(FadeIn(c, shift=0.3 * UP) for c in chips), lag_ratio=0.25), run_time=RUN)
        self.wait()

        # 標題靠上、底下一條線
        title = text("每個字都在看別的字", TITLE).to_edge(UP, buff=1.2)
        underline = Underline(title, color=GREY_B_3B, stroke_width=2)
        self.play(Write(title), Create(underline), run_time=RUN)
        self.wait()

        # 框住主角，其他調暗
        focus = chips[3]
        frame = look_at(focus)
        others = VGroup(*(c for c in chips if c is not focus))
        others.save_state()
        self.play(Create(frame), others.animate.set_opacity(DIM), run_time=QUICK)
        self.wait()

        # 調暗的東西用 Restore 還原。「指向誰」用彎的箭頭，都從下面繞，一條一條畫
        self.play(Restore(others), run_time=QUICK)
        arrows = VGroup(*(
            CurvedArrow(focus.get_bottom(), c.get_bottom(), angle=-TAU / 4 if c.get_x() < focus.get_x() else TAU / 4,
                        color=TEAL_3B, stroke_width=2, tip_length=0.15)
            for c in others))
        self.play(LaggedStart(*(Create(a) for a in arrows), lag_ratio=0.25), run_time=RUN)
        self.wait()

        # 結果從原來的圖形長出來：每張字卡複製一份，變成下面的長條
        weights = [0.55, 0.25, 0.05, 0.0, 0.15]
        bars = VGroup()
        for c, w in zip(chips, weights):
            bar = Rectangle(width=0.5, height=max(w * 4, 0.02), stroke_width=0, fill_color=BLUE_3B, fill_opacity=1)
            bar.next_to(c, DOWN, buff=3.2, aligned_edge=DOWN).align_to(DOWN * 4, DOWN)
            num = text(f"{w:.2f}", SMALL, GREY_A_3B).next_to(bar, UP, buff=0.1)
            bars.add(VGroup(bar, num))
        bars.remove(bars[3])
        sources = [c for c in chips if c is not focus]
        caption = text("各看多少", LABEL, GREY_B_3B).next_to(bars, DOWN, buff=0.5)
        self.play(LaggedStart(*(TransformFromCopy(s[0], b[0]) for s, b in zip(sources, bars)), lag_ratio=0.25),
                  run_time=RUN)
        self.play(LaggedStart(*(FadeIn(b[1], shift=0.2 * UP) for b in bars), lag_ratio=0.1), FadeIn(caption),
                  run_time=QUICK)
        self.wait()

        # 黃框移到答案上，停住。場景結尾不淡出到黑，停在最後的重點上
        # 箭頭只調暗線條：set_opacity 會連填色一起改，彎箭頭會變成一塊色塊
        self.play(frame.animate.become(look_at(bars[0])), arrows.animate.set_stroke(opacity=DIM), run_time=QUICK)
        self.wait(2)
