from __future__ import annotations

import re

from folivox.lang import CJKLanguage, register
from folivox.lang.rules import parse_units

DIGITS = "零一二三四五六七八九"
UNITS = ["", "十", "百", "千"]
BIG = ["", "万", "亿", "兆"]


def zh_int(n: int) -> str:
    """Chinese reading of a non-negative integer (simplified characters)."""
    if n == 0:
        return DIGITS[0]
    if n >= 10000 ** len(BIG):  # beyond 兆: read digit by digit
        return "".join(DIGITS[int(d)] for d in str(n))
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


MEASURE = "人个只条本位名件张辆台双把支种块次间家层点封所道门颗头首顶幅份杯瓶碗倍年"
TWO = {1: "两", 3: "两百", 4: "两千", 5: "两万"}


class Chinese(CJKLanguage):
    code, name, native = "zh", "Chinese", "中文"
    chapter_label, intro_label = "第{n}章", "序"
    cps = (2.5, 9.0)
    hallucinations = (r"(?:字幕|字幕由|中文字幕)[^。！？]*[。！？]?", r"(?:请不吝)?点赞\s*订阅[^。！？]*[。！？]?")
    units = parse_units("""
        km/h=公里每小时
        m/s=米每秒
        km²=平方公里
        m²=平方米
        cm²=平方厘米
        m³=立方米
        km=公里
        kg=公斤
        mg=毫克
        cm=厘米
        mm=毫米
        ml=毫升
        kHz=千赫兹
        MHz=兆赫兹
        GHz=吉赫兹
        kW=千瓦
        GB=吉字节
        MB=兆字节
        °C=摄氏度
        °F=华氏度
        °=度
        g=克
        m=米
        l=升
    """)

    def number(self, s: str) -> str:
        if re.search(r"[.,]", s):
            whole, frac = re.split(r"[.,]", s, maxsplit=1)
            return zh_int(int(whole)) + "点" + "".join(DIGITS[int(d)] for d in frac)
        return zh_int(int(s))

    def times(self, text: str) -> str:
        def one(m: re.Match) -> str:
            h, mi = int(m.group(1)), int(m.group(2))
            if h > 24 or mi > 59:
                return m.group(0)
            return f"{h}点" + (("零" if mi < 10 else "") + f"{mi}分" if mi else "")

        return re.sub(r"(?<![\d:.,/-])(\d{1,2}):(\d{2})(?![\d:])", one, text)

    def money(self, text: str) -> str:
        for sym, word in (("[¥￥]", "元"), (r"\$", "美元"), ("€", "欧元"), ("£", "英镑")):
            text = re.sub(rf"{sym}\s?(\d+(?:\.\d+)?)", rf"\1{word}", text)
        return text

    def counters(self, text: str) -> str:
        # a year is read digit by digit: 一九八四年; other numbers as numbers
        text = re.sub(r"(?<![\d.,])([12]\d{3})(?=年)", lambda m: "".join(DIGITS[int(d)] for d in m.group(1)), text)
        # «2个» is 两个, not 二个; but an ordinal stays 二: 第2层
        text = re.sub(rf"(?<![\d.,第])(2|20{{2,4}})(?=[{MEASURE}])",
                      lambda m: TWO.get(len(m.group(1)), m.group(0)), text)
        return re.sub(r"(\d+(?:\.\d+)?)%", r"百分之\1", text)


register(Chinese())
