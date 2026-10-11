from __future__ import annotations

import re

from folivox.lang import CJKLanguage, register
from folivox.lang.rules import ko_native, parse_units

# counters that take native Korean numerals: 세 명, 두 시간, 스무 살
COUNTERS = ("번째", "시간", "마리", "사람", "켤레", "송이", "그루", "자루", "그릇", "가지", "바퀴",
            "명", "개", "권", "살", "장", "잔", "병", "대", "곳", "채", "벌", "달", "시")


class Korean(CJKLanguage):
    code, name, native = "ko", "Korean", "한국어"
    chapter_label, intro_label = "제{n}장", "서문"
    cps = (3.0, 12.0)
    chapter_words = ()
    hallucinations = (r"시청해\s*주셔서 감사합니다\W*", r"구독과 좋아요[^.!?]*[.!?]?")
    SYMBOLS = {"%": "퍼센트", "&": "앤", "+": "플러스"}
    units = parse_units("""
        km/h=킬로미터 매시
        m/s=미터 매초
        km²=제곱킬로미터
        m²=제곱미터
        cm²=제곱센티미터
        m³=세제곱미터
        km=킬로미터
        kg=킬로그램
        mg=밀리그램
        cm=센티미터
        mm=밀리미터
        ml=밀리리터
        kHz=킬로헤르츠
        MHz=메가헤르츠
        GHz=기가헤르츠
        kW=킬로와트
        GB=기가바이트
        MB=메가바이트
        g=그램
        m=미터
        l=리터
    """)

    def sentences(self, text: str) -> list[str]:  # Korean uses spaces and Western punctuation
        parts = re.split(r"(?<=[.!?…。！？])\s+", text)
        return [p.strip() for p in parts if p.strip()]

    def times(self, text: str) -> str:
        def one(m: re.Match) -> str:
            h, mi = int(m.group(1)), int(m.group(2))
            if h > 24 or mi > 59:
                return m.group(0)
            return f"{h}시" + (f" {mi}분" if mi else "")

        return re.sub(r"(?<![\d:.,/-])(\d{1,2}):(\d{2})(?![\d:])", one, text)

    def money(self, text: str) -> str:
        for sym, word in (("[₩￦]", "원"), (r"\$", "달러"), ("€", "유로"), ("£", "파운드"), ("[¥￥]", "엔")):
            text = re.sub(rf"{sym}\s?(\d+(?:\.\d+)?)", rf"\1{word}", text)
        return text

    def measures(self, text: str) -> str:
        text = re.sub(r"(?<![\d.,])(\d+(?:\.\d+)?)\s?°C", r"섭씨 \1도", text)
        text = re.sub(r"(?<![\d.,])(\d+(?:\.\d+)?)\s?°F", r"화씨 \1도", text)
        return super().measures(text)

    def counters(self, text: str) -> str:
        # 6월 → 유월, 10월 → 시월 (irregular); other months are Sino-Korean
        text = re.sub(r"(?<![\d.,])6월", "유월", text)
        text = re.sub(r"(?<![\d.,])10월", "시월", text)

        def native(m: re.Match) -> str:
            n, counter = int(m.group(1)), m.group(2)
            if counter == "번째" and n == 1:
                return "첫 번째"
            word = ko_native(n)
            return f"{word} {counter}" if word else f"{n} {counter}"

        alts = "|".join(COUNTERS)
        return re.sub(rf"(?<![\d.,])(\d+)\s?({alts})(?!월)", native, text)


register(Korean())
