"""Chinese text rules shared by render.py (captions) and pack_transcripts.py.

Cue length is measured in display width (CJK and full-width punctuation
count 2, everything else 1), since a Latin word inside Chinese speech should
not count each letter as a full character.

日文也用這裡的規則（同樣不加空格、同樣用字寬計算），只是斷詞改用 BudouX、
不做簡繁轉換。檔名維持 zh_text 以免動到各處的 import。
"""

from __future__ import annotations

import functools
import logging
import re
import unicodedata
import warnings


ZH_PUNCT_BREAK = set("，。！？；：、,.!?;:")
ZH_TRAILING_STRIP = "，。、；：,.;:"  # keep ？！ — they change the meaning
# 句中的停頓標點換成 En space（約半個字寬）：全形空格太開、一般空格太窄，
# 兩個半形空格又可能被播放器合併成一個（2026-10-09 比較過）
ZH_INNER_SEP = " "
# 中文停頓標點；英文的 ,;: 夾在兩個數字中間時（1,000、10:30）不算
_INNER_PUNCT = re.compile(r"\s*(?:[，、；：。]|(?<!\d)[,;:]|[,;:](?!\d))\s*")


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _is_latin(c: str) -> bool:
    return c.isascii() and c.isalnum()


def _is_cjk_punct(c: str) -> bool:
    return unicodedata.category(c).startswith("P") and display_width(c) == 2


def is_punct(text: str) -> bool:
    """True if the token is punctuation only (Scribe gives "，" "。" their own token)."""
    text = text.strip()
    return bool(text) and all(unicodedata.category(c).startswith("P") for c in text)


# jieba and OpenCC load on first use, so English-only runs never import them.
@functools.cache
def _jieba():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # jieba 0.42 has invalid escapes in its regexes
        import jieba
    jieba.setLogLevel(logging.WARNING)  # silence "Building prefix dict..." on first cut
    return jieba


@functools.cache
def _budoux_ja():
    # 日文斷詞：BudouX 依文節切開（終章の | 朗読劇の | 前に），只有日文影片才載入
    import budoux
    return budoux.load_default_japanese_parser()


def _segment(text: str, lang: str) -> list[str]:
    if lang == "ja":
        return _budoux_ja().parse(text)
    return _jieba().lcut(text)


@functools.cache
def _opencc():
    import opencc
    return opencc.OpenCC("s2twp")  # Simplified → Traditional, Taiwan wording (视频 → 影片)


def word_boundaries(texts: list[str], lang: str = "zh") -> set[int]:
    """Indices of tokens that end a word, so a cue may break after them.

    The tokens are joined (a space beside Latin words, as in join_zh, so
    "Claude" "Code" stay two words), cut into words with jieba, and token i
    counts when its end lands on a word's end. The last token always does.
    lang="ja" 改用 BudouX 的文節當作「詞」。
    """
    if not texts:
        return set()
    joined = ""
    token_ends: list[int] = []
    for t in texts:
        t = t.strip()
        if joined and t and (_is_latin(joined[-1]) or _is_latin(t[0])):
            joined += " "
        joined += t
        token_ends.append(len(joined))
    word_ends: set[int] = set()
    pos = 0
    for word in _segment(joined, lang):
        pos += len(word)
        word_ends.add(pos)
    out = {i for i, end in enumerate(token_ends) if end in word_ends}
    out.add(len(texts) - 1)
    return out


def is_number(text: str) -> bool:
    """數字 token（100、95、3.5、1,000），斷句時不和後面的單位拆開。"""
    text = text.strip()
    return any(c.isdigit() for c in text) and all(c.isdigit() or c in ".,%" for c in text)


def starts_cjk(text: str) -> bool:
    """token 是否以中文字開頭（不含標點）。"""
    text = text.strip()
    return bool(text) and display_width(text[0]) == 2 and not is_punct(text[0])


def inner_punct_to_space(text: str) -> str:
    """句中的停頓標點換成 En space，前後原有的空格一併去掉；？！ 保留。"""
    return _INNER_PUNCT.sub(ZH_INNER_SEP, text)


def to_traditional(text: str) -> str:
    return _opencc().convert(text)


def join_zh(texts: list[str], space_digits: bool = True) -> str:
    """Join Chinese tokens: no space between Chinese words, one space where
    either neighbour is a Latin letter or digit ("用 Claude Code 剪片").
    space_digits=False（日文）：數字兩邊不加空格（第2部、21時），英文單字照樣加。"""
    def spaced(c: str) -> bool:
        return _is_latin(c) and (space_digits or not c.isdigit())

    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if out:
            a, b = out[-1], t[0]
            if (spaced(a) or spaced(b)) and not (_is_cjk_punct(a) or _is_cjk_punct(b)):
                out += " "
        out += t
    return out


def transcript_lang(transcript: dict) -> str | None:
    """逐字稿是中文（"zh"）、日文（"ja"），還是要加空格的語言（None）。

    中文：Scribe 標記為中文，或沒有假名且一半以上的字是漢字。
    日文：標記 ja／jpn，或文字裡有假名。
    """
    code = (transcript.get("language_code") or "").lower()
    if code.startswith(("zh", "cmn", "yue")):
        return "zh"
    # 日文也大量使用漢字，只看漢字比例會被誤判成中文
    if code in ("ja", "jpn"):
        return "ja"
    text = "".join(w.get("text") or "" for w in transcript.get("words", []) if w.get("type") == "word")
    # 有平假名或片假名就是日文（沒有標記、或 Scribe 標錯語言時）。
    # 只算假名本身：中點「・」（U+30FB）在中文譯名裡也會出現（哈利・波特）
    if any("ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" for c in text):
        return "ja"
    letters = [c for c in text if c.isalpha()]
    cjk = sum(1 for c in letters if "㐀" <= c <= "鿿")
    return "zh" if letters and cjk * 2 > len(letters) else None


def looks_chinese(transcript: dict) -> bool:
    """True if Scribe tagged the transcript as Chinese, or most of its letters
    are CJK ideographs. Used to warn when Chinese speech gets English rules.
    Japanese (tagged ja/jpn, or containing kana) is never Chinese."""
    return transcript_lang(transcript) == "zh"
