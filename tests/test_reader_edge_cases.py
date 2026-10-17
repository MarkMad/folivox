"""Edge cases found in an audit of readers and normalisers."""

import zipfile

import pytest

from folivox.lang import get
from folivox.readers import read_book


def test_unsupported_lang_metadata_falls_back_to_detection(tmp_path):
    p = tmp_path / "book.fb2"
    p.write_text('<FictionBook><description><title-info><book-title>T</book-title><lang>und</lang>'
                 '</title-info></description><body><section><title><p>One</p></title>'
                 '<p>The cat sat on the mat and it was happy with the dog.</p></section></body></FictionBook>',
                 encoding="utf-8")
    book = read_book(p)
    assert book.lang == "en"
    assert book.chapters()


def test_fb2_zip_without_fb2_raises_value_error(tmp_path):
    p = tmp_path / "book.fb2.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("readme.txt", "nothing")
    with pytest.raises(ValueError):
        read_book(p)


@pytest.mark.parametrize("code", ["ru", "it", "zh", "ja"])
def test_huge_numbers_do_not_crash(code):
    for s in ("1" + "0" * 16, "1" + "0" * 16 + ".5", "1" + "0" * 40, "1" + "0" * 55):
        assert get(code).normalize(s)
