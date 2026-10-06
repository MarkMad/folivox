"""Regenerate the synthetic test books: ``uv run python tests/fixtures/make_fixtures.py``.

All text here is written for the tests (public domain). Every book has the same logical shape:
title «Тестовая книга», author «Иван Тестов», two chapters (+ a part level where the format
allows it), Russian text with dialogue, numbers and a footnote that must be skipped.
"""

from __future__ import annotations

import base64
from pathlib import Path

HERE = Path(__file__).parent

CH1 = [
    "Утро выдалось холодным. В 7:30 Пётр вышел из дома № 12 на улице Ленина.",
    "— Ты куда? — спросила соседка.",
    "— На работу, — ответил он и пошёл дальше.",
]
CH2 = [
    "В 1999 году всё было иначе. Цены выросли на 15%, а зарплата — нет.",
    "Он купил 3 кг яблок и т. д. Вечером позвонил брату.",
]


def _jpeg() -> bytes:
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 16, 16), 0)
    pix.set_rect(pix.irect, (200, 40, 40))
    return pix.tobytes("jpeg")


JPEG = _jpeg()


def fb2() -> None:
    p = lambda t: f"<p>{t}</p>"  # noqa: E731
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description><title-info>
 <genre>prose</genre><author><first-name>Иван</first-name><last-name>Тестов</last-name></author>
 <book-title>Тестовая книга</book-title>
 <annotation><p>Короткая аннотация.</p></annotation>
 <date value="2024-01-01">2024</date>
 <coverpage><image l:href="#cover.jpg"/></coverpage><lang>ru</lang>
</title-info></description>
<body>
 <title><p>Иван Тестов</p><p>Тестовая книга</p></title>
 <section>
  <title><p>Часть первая</p></title>
  <epigraph><p>Всё течёт, всё меняется.</p><text-author>Гераклит</text-author></epigraph>
  <section>
   <title><p>Глава 1</p><p>Утро</p></title>
   {"".join(p(t) for t in CH1[:1])}
   <p>Сноска здесь<a l:href="#n1" type="note">[1]</a> не читается.</p>
   {"".join(p(t) for t in CH1[1:])}
   <poem><stanza><v>Мороз и солнце;</v><v>день чудесный!</v></stanza></poem>
  </section>
  <section>
   <title><p>2</p></title>
   <subtitle>* * *</subtitle>
   {"".join(p(t) for t in CH2)}
   <cite><p>Цитата из письма.</p></cite>
  </section>
 </section>
</body>
<body name="notes">
 <section id="n1"><title><p>1</p></title><p>Текст сноски, который не нужно озвучивать.</p></section>
</body>
<binary id="cover.jpg" content-type="image/jpeg">{base64.b64encode(JPEG).decode()}</binary>
</FictionBook>
"""
    (HERE / "book.fb2").write_text(xml, encoding="utf-8")


def txt() -> None:
    lines = ["Иван Тестов", "", "ЧАСТЬ ПЕРВАЯ", "", "ГЛАВА I", "Утро", ""]
    for t in CH1:
        lines += [t, ""]
    lines += ["Глава 2", ""]
    for t in CH2:
        # hard-wrapped paragraph
        mid = len(t) // 2
        cut = t.rfind(" ", 0, mid)
        lines += [t[:cut], t[cut + 1:], ""]
    (HERE / "Иван Тестов - Тестовая книга.txt").write_bytes("\r\n".join(lines).encode("cp1251"))


def docx() -> None:
    import docx as d

    doc = d.Document()
    doc.core_properties.title = "Тестовая книга"
    doc.core_properties.author = "Иван Тестов"
    doc.add_paragraph("Тестовая книга", style="Title")
    doc.add_heading("Часть первая", level=1)
    doc.add_heading("Глава 1. Утро", level=2)
    for t in CH1:
        doc.add_paragraph(t)
    doc.add_heading("Глава 2", level=2)
    for t in CH2:
        doc.add_paragraph(t)
    doc.save(HERE / "book.docx")


def epub() -> None:
    from ebooklib import epub as e

    b = e.EpubBook()
    b.set_identifier("folivox-test")
    b.set_title("Тестовая книга")
    b.set_language("ru")
    b.add_author("Иван Тестов")
    b.set_cover("cover.jpg", JPEG)
    c1 = e.EpubHtml(title="Глава 1. Утро", file_name="ch1.xhtml", lang="ru")
    c1.content = ("<html><body><h1>Глава 1. Утро</h1>"
                  "<div class='epigraph'><p>Всё течёт, всё меняется.</p></div>"
                  + "".join(f"<p>{t}</p>" for t in CH1)
                  + "<p>Сноска здесь<a epub:type='noteref' href='notes.xhtml#n1'>1</a> не читается.</p>"
                  "</body></html>")
    # chapter 2 and 3 live in one file, separated by anchors
    c2 = e.EpubHtml(title="Глава 2", file_name="ch2.xhtml", lang="ru")
    c2.content = ("<html><body><h2 id='g2'>Глава 2</h2>" + "".join(f"<p>{t}</p>" for t in CH2)
                  + "<h2 id='g3'>Глава 3</h2><p>Короткая третья глава.</p></body></html>")
    notes = e.EpubHtml(title="Примечания", file_name="notes.xhtml", lang="ru")
    notes.content = ("<html><body><aside epub:type='footnote' id='n1'><p>Текст сноски.</p></aside>"
                     "</body></html>")
    for c in (c1, c2, notes):
        b.add_item(c)
    b.toc = [e.Link("ch1.xhtml", "Глава 1. Утро", "c1"), e.Link("ch2.xhtml#g2", "Глава 2", "c2"),
             e.Link("ch2.xhtml#g3", "Глава 3", "c3")]
    b.add_item(e.EpubNcx())
    b.add_item(e.EpubNav())
    b.spine = ["nav", c1, c2, notes]
    e.write_epub(str(HERE / "book.epub"), b)


def pdf() -> None:
    import pymupdf

    doc = pymupdf.open()
    css = "body{font-family:sans-serif;font-size:11pt} h1{font-size:20pt}"
    pages = [
        ("Глава 1. Утро", CH1 + ["Этот абзац переходит на следующую страницу и продолжается"]),
        (None, ["там, где его никто не ждёт."]),
        ("Глава 2", CH2),
    ]
    toc = []
    for i, (title, paras) in enumerate(pages):
        page = doc.new_page(width=420, height=595)
        page.insert_htmlbox(pymupdf.Rect(40, 10, 380, 30), "<p style='font-size:8pt'>Тестовая книга</p>",
                            css=css)
        html = (f"<h1>{title}</h1>" if title else "") + "".join(f"<p>{t}</p>" for t in paras)
        page.insert_htmlbox(pymupdf.Rect(40, 60, 380, 540), html, css=css)
        page.insert_htmlbox(pymupdf.Rect(190, 565, 230, 585), f"<p style='font-size:8pt'>{i + 1}</p>", css=css)
        if title:
            toc.append([1, title, i + 1])
    doc.set_toc(toc)
    doc.set_metadata({"title": "Тестовая книга", "author": "Иван Тестов"})
    doc.subset_fonts()
    doc.save(HERE / "book.pdf", garbage=4, deflate=True)


if __name__ == "__main__":
    fb2()
    txt()
    docx()
    epub()
    pdf()
    print("fixtures written to", HERE)
