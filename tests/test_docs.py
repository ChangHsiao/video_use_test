"""文件之間的連結：每個 .md 裡的相對連結都要指到存在的檔案。搬資料夾之後最容易壞的就是這個。"""

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[1]
# 檢查 repo 自己的文件：根目錄的 .md 和各層資料夾。不檢查外部引入的 skill（skills/）、套件和使用者放進來的內容資料夾
LAYERS = ("sop", "recipes", "styles", "brands", "templates")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def tracked_docs():
    yield from REPO.glob("*.md")
    for layer in LAYERS:
        yield from (p for p in (REPO / layer).rglob("*.md") if "node_modules" not in p.parts)


class DocLinksTest(unittest.TestCase):
    def test_relative_links_resolve(self):
        broken = []
        for doc in tracked_docs():
            text = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.S)
            for target in LINK.findall(text):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                path = unquote(target.split("#")[0])
                if path and not (doc.parent / path).exists():
                    broken.append(f"{doc.relative_to(REPO)} → {target}")
        self.assertEqual(broken, [], "壞掉的連結：\n" + "\n".join(broken))


if __name__ == "__main__":
    unittest.main()
