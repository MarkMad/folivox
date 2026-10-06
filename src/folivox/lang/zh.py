from __future__ import annotations

import re

from folivox.lang import CJKLanguage, register

DIGITS = "零一二三四五六七八九"
UNITS = ["", "十", "百", "千"]
BIG = ["", "万", "亿", "兆"]


def zh_int(n: int) -> str:
    """Chinese reading of a non-negative integer (simplified characters)."""
    if n == 0:
        return DIGITS[0]
    groups: list[int] = []
    while n:
        groups.append(n % 10000)
        n //= 10000
    out = ""
    zero = False
    for gi in range(len(groups) - 1, -1, -1):
        g = groups[gi]
        if g == 0:
            zero = bool(out)
            continue
        if out and (zero or g < 1000):
            out += DIGITS[0]
        part = ""
        gzero = False
        for pos in range(3, -1, -1):
            d = g // 10 ** pos % 10
            if d == 0:
                gzero = bool(part)
                continue
            if gzero:
                part += DIGITS[0]
                gzero = False
            part += DIGITS[d] + UNITS[pos]
        out += part + BIG[gi]
        zero = False
    if out.startswith("一十"):
        out = out[1:]
    return out


class Chinese(CJKLanguage):
    code, name, native = "zh", "Chinese", "中文"
    chapter_label, intro_label = "第{n}章", "序"
    cps = (2.5, 9.0)
    hallucinations = (r"(?:字幕|字幕由|中文字幕)[^。！？]*[。！？]?", r"(?:请不吝)?点赞\s*订阅[^。！？]*[。！？]?")

    def number(self, s: str) -> str:
        if re.search(r"[.,]", s):
            whole, frac = re.split(r"[.,]", s, maxsplit=1)
            return zh_int(int(whole)) + "点" + "".join(DIGITS[int(d)] for d in frac)
        if len(s) == 4 and s[0] in "12":  # years are read digit by digit: 一九八四
            return "".join(DIGITS[int(d)] for d in s)
        return zh_int(int(s))

    def numbers(self, text: str) -> str:
        text = re.sub(r"(\d+(?:\.\d+)?)%", lambda m: "百分之" + self.number(m.group(1)), text)
        return re.sub(r"\d+(?:\.\d+)?", lambda m: self.number(m.group(0)), text)


register(Chinese())
