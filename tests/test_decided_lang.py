"""Decided fixes: uk/be warning, Rosetta detection, unreadable PDFs, DOCX tables."""

from __future__ import annotations

import subprocess

import pytest

from folivox.lang.detect import unsupported_cyrillic
from folivox.readers import UnreadableBook, UnsupportedFormat, read_book

UK = ("Це була звичайна історія про їжака, який жив у лісі і мріяв про великі пригоди. "
      "Ґанок був старий, є що згадати. ") * 10
BE = "Гэта была звычайная гісторыя пра вожыка, які жыў у лесе і марыў пра вялікія прыгоды. Ён заўсёды ўсміхаўся. " * 10
RU = "Это была обычная история про ежика, который жил в лесу и мечтал о больших приключениях. " * 10


def test_unsupported_cyrillic():
    assert unsupported_cyrillic(UK) == "uk"
    assert unsupported_cyrillic(BE) == "be"
    assert unsupported_cyrillic(RU) is None
    assert unsupported_cyrillic("Київ") is None  # too short to tell


@pytest.mark.parametrize("text,name", [(UK, "lang_uk"), (BE, "lang_be")])
def test_txt_book_warns_and_reads_as_russian(tmp_path, text, name):
    f = tmp_path / "b.txt"
    f.write_text(text, encoding="utf-8")
    book = read_book(f)
    assert book.lang == "ru"
    assert book.warnings == [name]


def test_russian_book_has_no_warning(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text(RU, encoding="utf-8")
    book = read_book(f)
    assert book.lang == "ru" and book.warnings == []


def test_metadata_lang_uk(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.core_properties.language = "uk-UA"
    d.add_paragraph(RU)
    f = tmp_path / "b.docx"
    d.save(f)
    book = read_book(f)
    assert book.lang == "ru" and book.warnings == ["lang_uk"]


def test_docx_tables_in_order(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("Перед таблицей.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "А1", "Б1"
    t.cell(1, 0).text = "А2"
    t.cell(1, 0).merge(t.cell(1, 1))
    d.add_paragraph("После таблицы.")
    f = tmp_path / "t.docx"
    d.save(f)
    texts = [b.text for s in read_book(f).sections for sec in s.walk() for b in sec.blocks]
    assert texts == ["Перед таблицей.", "А1", "Б1", "А2", "После таблицы."]


def _pdf(tmp_path, text: str | None, password: str | None = None):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    else:
        page.draw_rect(pymupdf.Rect(50, 50, 200, 200), fill=(0, 0, 0))
    f = tmp_path / "b.pdf"
    kw = {}
    if password:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "x")
    doc.save(str(f), **kw)
    doc.close()
    return f


def test_pdf_without_text_layer(tmp_path):
    with pytest.raises(UnreadableBook, match="no text layer"):
        read_book(_pdf(tmp_path, None))


def test_pdf_with_password(tmp_path):
    with pytest.raises(UnsupportedFormat, match="password"):
        read_book(_pdf(tmp_path, "Hello world, this is text.", password="secret"))


def test_pdf_with_text_reads(tmp_path):
    book = read_book(_pdf(tmp_path, "Hello world, this is text."))
    assert book.chars > 0


def test_under_rosetta(monkeypatch):
    from folivox.tts import native_setup

    native_setup.under_rosetta.cache_clear()
    monkeypatch.setattr(native_setup.sys, "platform", "darwin")
    monkeypatch.setattr(native_setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="1\n"))
    assert native_setup.under_rosetta() is True
    native_setup.under_rosetta.cache_clear()
    monkeypatch.setattr(native_setup.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert native_setup.under_rosetta() is False
    native_setup.under_rosetta.cache_clear()


def test_doctor_advice_rosetta():
    from folivox.diag import advice

    assert any("Rosetta" in t for t in advice({"rosetta": True, "device": "cpu"}))
    assert not any("Rosetta" in t for t in advice({"device": "cpu"}))


def test_cli_prints_warning_unless_lang(tmp_path, capsys):
    from folivox import cli

    f = tmp_path / "b.txt"
    f.write_text(UK, encoding="utf-8")
    cli._load(f)
    assert "Ukrainian" in capsys.readouterr().out
    cli._load(f, "ru")
    assert "Ukrainian" not in capsys.readouterr().out
