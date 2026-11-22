"""風格、品牌、版型的登記處：引擎只透過這裡讀 styles/、brands/，不寫死任何顏色、字級或檔案路徑。

三種東西都「放一個資料夾就生效」，不用改程式：
    styles/<名稱>/style.json   一種視覺語言（版面數值、顏色），用 "layout" 指定版型、"brand" 指定品牌（選填）
    brands/<名稱>/brand.json   一個品牌（顏色、字型、logo、片尾、口播收尾），長片和短片共用
    版型（layout）             一種畫面排法；每個版型在這裡登記一個檢查函式，style.json 照它的欄位寫

找素材的順序（Style.asset）：影片資料夾 → 風格資料夾 → 品牌資料夾，前面的可以蓋過後面的。
欄位說明見 styles/README.md、brands/README.md；整體分層見 ARCHITECTURE.md。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
STYLES_DIR = REPO / "styles"
BRANDS_DIR = REPO / "brands"
DEFAULT_LAYOUT = "broll_top"  # style.json 沒寫 layout 時用這個（科普短片的版型，舊的 style.json 不用改）


# style.json、brand.json 有問題時用的錯誤，訊息直接給使用者看
class ConfigError(Exception):
    pass


# "#rrggbb" → (r, g, b)
def hex_rgb(color):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
        raise ValueError(f"顏色要寫成 #rrggbb：{color}")
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} 的格式不對：{e!r}")


@dataclass(frozen=True)
class Brand:
    name: str
    root: Path
    data: dict

    @property
    def colors(self):
        return self.data.get("colors", {})

    # 品牌資料夾裡的檔案；不存在回傳 None
    def asset(self, rel):
        p = self.root / rel
        return p if p.is_file() else None


@dataclass(frozen=True)
class Style:
    name: str
    root: Path
    data: dict
    brand: Brand | None = None
    colors: dict = field(default_factory=dict)  # 品牌的顏色加上風格自己的顏色（同名時風格優先）

    @property
    def layout(self):
        return self.data.get("layout", DEFAULT_LAYOUT)

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    # 依序在 extra（影片資料夾）、風格資料夾、品牌資料夾找 rel；可以給好幾個候選路徑，回傳第一個存在的。
    # 絕對路徑（例如系統字型）直接檢查。都找不到就報錯，列出找過的地方
    def asset(self, *candidates, extra=()):
        roots = [Path(r) for r in extra] + [self.root] + ([self.brand.root] if self.brand else [])
        tried = []
        for rel in candidates:
            for p in ([Path(rel)] if Path(rel).is_absolute() else [r / rel for r in roots]):
                tried.append(str(p))
                if p.is_file():
                    return p
        raise ConfigError(f"風格「{self.name}」找不到素材，找過：{'、'.join(tried)}")

    # 顏色名稱 → (r, g, b)
    def rgb(self, name):
        return hex_rgb(self.colors[name])


# ---------- 版型：每個版型登記一個檢查函式，style.json 照它的欄位寫 ----------

LAYOUTS: dict[str, Callable[[dict, dict], list]] = {}


# 登記版型。檢查函式拿到 (style.json 內容, 合併後的顏色)，回傳這個風格用到的顏色名稱，
# 欄位缺少或型別不對時直接丟 KeyError / TypeError / ValueError
def register_layout(name):
    def deco(fn):
        LAYOUTS[name] = fn
        return fn
    return deco


def _numbers(spec, *keys):
    for k in keys:
        float(spec[k])


@register_layout("broll_top")
def _check_broll_top(style, colors):
    """科普短片（helpers/compose.py）：B-roll 放上方、模糊背景、頂部標題、數字卡、段落標題卡、雙語字幕。"""
    specs = [style["title"], *style["number"].values(), *style["section"]["text"].values(), *style["subtitle"].values()]
    for s in specs:
        _numbers(s, "size", "y")
    _numbers(style["broll"], "top", "bg_zoom", "bg_dim")
    for c in style["section"]["background"]:
        hex_rgb(c)
    return [s["color"] for s in specs] + [style["title"]["accent"], *style["number_colors"]]


@register_layout("news_band")
def _check_news_band(style, colors):
    """新聞短片（helpers/news_short.py）：模糊底加主畫面帶、資訊卡、原聲卡、雙語字幕、調色與轉場。"""
    _numbers(style["canvas"], "w", "h", "fps")
    _numbers(style["band"], "y", "h", "fade", "ticker_trim")
    _numbers(style["title"], "size", "y")
    _numbers(style["info"], "y", "tag_size", "line_size")
    _numbers(style["sot_card"], "y", "size", "source_size")
    for s in style["subtitle"].values():
        _numbers(s, "size", "y", "min_size")
    _numbers(style["grade"], "contrast", "saturation", "gamma", "push", "grain")
    _numbers(style["transitions"], "in_block", "between_blocks", "sot_pre", "sot_post", "vo_hold")
    return [style["title"]["color"], style["title"]["accent"], style["info"]["tag_bg"], style["sot_card"]["tag_bg"],
            *(s["color"] for s in style["subtitle"].values())]


# ---------- 讀取 ----------

def available(root, filename):
    return sorted(d.name for d in Path(root).iterdir() if (d / filename).is_file()) if Path(root).is_dir() else []


def load_brand(name, root=None):
    root = Path(root or BRANDS_DIR)
    path = root / str(name) / "brand.json"
    if not path.is_file():
        raise ConfigError(f"找不到品牌「{name}」（{path}）。可用的品牌：{'、'.join(available(root, 'brand.json')) or '沒有'}")
    data = _read_json(path)
    try:
        for c in data.get("colors", {}).values():
            hex_rgb(c)
    except ValueError as e:
        raise ConfigError(f"{path} 的格式不對：{e!r}（欄位說明見 brands/README.md）")
    return Brand(str(name), path.parent, data)


# 讀 styles/<name>/style.json：接上品牌、照版型檢查欄位；找不到、缺欄位、用到沒定義的顏色都報錯
def load_style(name, root=None, brands_root=None):
    root = Path(root or STYLES_DIR)
    path = root / str(name) / "style.json"
    if not path.is_file():
        raise ConfigError(f"找不到風格「{name}」（{path}）。可用的風格：{'、'.join(available(root, 'style.json'))}")
    data = _read_json(path)
    brand = load_brand(data["brand"], brands_root) if data.get("brand") else None
    colors = {**(brand.colors if brand else {}), **data.get("colors", {})}
    layout = data.get("layout", DEFAULT_LAYOUT)
    if layout not in LAYOUTS:
        raise ConfigError(f"{path} 的 layout「{layout}」沒有登記。可用的版型：{'、'.join(sorted(LAYOUTS))}")
    try:
        used = LAYOUTS[layout](data, colors)
        for c in colors.values():
            hex_rgb(c)
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"{path} 的格式不對：{e!r}（欄位說明見 styles/README.md）")
    missing = sorted({c for c in used if c not in colors})
    if missing:
        raise ConfigError(f"{path} 用到 colors 裡沒有的顏色：{'、'.join(missing)}")
    return Style(str(name), path.parent, data, brand, colors)
