"""Audit regressions for the book readers: broken EPUB metadata / manifests, junk in fb2.zip, TXT encodings."""

from __future__ import annotations

import zipfile

from folivox.lang.detect import detect
from folivox.readers import read_book
from folivox.readers.txt import decode

_CONTAINER = ("<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
              "<rootfiles><rootfile full-path='OEBPS/c.opf' media-type='application/oebps-package+xml'/>"
              "</rootfiles></container>")


def _epub(path, meta: str, manifest: str = "", spine: str = "<itemref idref='c1'/>"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/c.opf", (
            "<?xml version='1.0'?><package xmlns='http://www.idpf.org/2007/opf' version='2.0' "
            "unique-identifier='id'><metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>"
            f"<dc:identifier id='id'>x</dc:identifier>{meta}</metadata><manifest>"
            f"<item id='c1' href='c1.xhtml' media-type='application/xhtml+xml'/>{manifest}</manifest>"
            f"<spine>{spine}</spine></package>"))
        z.writestr("OEBPS/c1.xhtml", "<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>Chapter one</h1>"
                                     "<p>He walked into the room and it was the end of the day.</p></body></html>")
    return path


def test_epub_empty_metadata_elements(tmp_path):
    book = read_book(_epub(tmp_path / "Dune.epub", "<dc:title/><dc:creator/><dc:date/><dc:description/>"))
    assert book.title == "Dune" and book.authors == [] and book.lang == "en"
    assert book.sections[0].title == "Chapter one"


def test_epub_manifest_file_missing_from_archive(tmp_path):
    path = _epub(tmp_path / "b.epub", "<dc:title>T</dc:title><dc:language>en</dc:language>",
                 manifest="<item id='c2' href='gone.xhtml' media-type='application/xhtml+xml'/>",
                 spine="<itemref idref='c1'/><itemref idref='c2'/>")
    book = read_book(path)
    assert [s.title for s in book.sections] == ["Chapter one"]


def test_fb2_zip_with_macos_resource_fork_first(tmp_path):
    fb2 = ("<?xml version='1.0' encoding='utf-8'?><FictionBook xmlns='http://www.gribuser.ru/xml/fictionbook/2.0'>"
           "<description><title-info><book-title>Книга</book-title><lang>ru</lang></title-info></description>"
           "<body><section><title><p>Глава 1</p></title><p>Текст главы.</p></section></body></FictionBook>")
    path = tmp_path / "m.fb2.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("__MACOSX/._m.fb2", b"\x00\x05\x16\x07junk")
        z.writestr("m.fb2", fb2)
    book = read_book(path)
    assert book.title == "Книга" and book.sections[0].title == "Глава 1"


def test_txt_cp1252_is_not_read_as_cyrillic():
    text = "Il était une fois une légende très connue, à côté de la forêt où l'élève était."
    assert decode(text.encode("cp1252")) == text


def test_txt_cyrillic_single_byte_still_detected():
    text = "Жили-были дед и баба, и была у них курочка ряба."
    assert decode(text.encode("cp1251")) == text
    assert decode(text.encode("koi8-r")) == text


def test_txt_utf16_without_bom():
    text = "Жили-были дед и баба, и была у них курочка ряба."
    assert decode(text.encode("utf-16-le")) == text
    assert decode(text.encode("utf-16-be")) == text
    assert decode(b"plain ascii text") == "plain ascii text"


def test_detect_latin_without_function_words_is_not_russian():
    assert detect("Dune. Arrakis. Paul Atreides.") == "en"
