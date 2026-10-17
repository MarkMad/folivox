from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import CJKLanguage, register
from folivox.lang.rules import parse_units


class Japanese(CJKLanguage):
    code, name, native = "ja", "Japanese", "日本語"
    chapter_label, intro_label = "第{n}章", "序章"
    cps = (3.0, 12.0)
    hallucinations = (r"ご視聴ありがとうございました\W*", r"(?:チャンネル登録|字幕)[^。！？]*[。！？]?")
    SYMBOLS = {"%": "パーセント", "&": "と", "+": "プラス", "=": "イコール"}
    units = parse_units("""
        km/h=キロメートル毎時
        m/s=メートル毎秒
        km²=平方キロメートル
        m²=平方メートル
        cm²=平方センチメートル
        m³=立方メートル
        km=キロメートル
        kg=キログラム
        mg=ミリグラム
        cm=センチメートル
        mm=ミリメートル
        ml=ミリリットル
        kHz=キロヘルツ
        MHz=メガヘルツ
        GHz=ギガヘルツ
        kW=キロワット
        GB=ギガバイト
        MB=メガバイト
        °C=度
        °F=華氏度
        °=度
        g=グラム
        m=メートル
        l=リットル
    """)

    def number(self, s: str) -> str:
        try:
            return num2words(float(s) if "." in s else int(s), lang="ja")
        except (NotImplementedError, ValueError, OverflowError, KeyError, IndexError):
            return s

    def times(self, text: str) -> str:
        def one(m: re.Match) -> str:
            h, mi = int(m.group(1)), int(m.group(2))
            if h > 24 or mi > 59:
                return m.group(0)
            return f"{h}時" + (f"{mi}分" if mi else "")

        return re.sub(r"(?<![\d:.,/-])(\d{1,2}):(\d{2})(?![\d:])", one, text)

    def money(self, text: str) -> str:
        for sym, word in (("[¥￥]", "円"), (r"\$", "ドル"), ("€", "ユーロ"), ("£", "ポンド")):
            text = re.sub(rf"{sym}\s?(\d+(?:\.\d+)?)", rf"\1{word}", text)
        return text


register(Japanese())
