"""Remotion props for a brand's outro A (數據流), read from brand.json so no outro text lives in code.

Usage:
  python helpers/outro_props.py --brand BRAND [--series KEY]
  npx remotion render src/index.ts OutroA-3s out.mp4 --props="$(python helpers/outro_props.py --brand BRAND)"

The text comes from the brand (or from series.<KEY> with --series), the same rule at both levels:
  slogan  outro_a.slogan, else slogan      footer  outro_a.footer (empty when not set)
name / nameEn are always the brand's (brand.json name, name_en).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402


def outro_props(brand: registry.Brand, series: str | None = None) -> dict[str, str]:
    data = brand.data
    names = {"name": data["name"], "nameEn": data.get("name_en", "")}
    if series:
        if series not in data.get("series", {}):
            raise registry.ConfigError(f"brand.json 沒有系列「{series}」。有的系列：{'、'.join(data.get('series', {})) or '沒有'}")
        data = data["series"][series]
    outro = data.get("outro_a", {})
    return {**names, "slogan": outro.get("slogan") or data.get("slogan", ""), "footer": outro.get("footer", "")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--brand", required=True)
    ap.add_argument("--series", help="a key of brand.json series; omit for the brand-level outro")
    a = ap.parse_args()
    print(json.dumps(outro_props(registry.load_brand(a.brand), a.series), ensure_ascii=False))


if __name__ == "__main__":
    main()
