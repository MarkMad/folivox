import ast
import re
from pathlib import Path

from folivox.i18n import _

SRC = Path(__file__).parent.parent / "src" / "folivox"


def test_shim_formats():
    assert _("Removed {id}", id="x") == "Removed x"
    assert _("plain") == "plain"


def test_source_has_no_hardcoded_russian_messages():
    # the CLI is English only; Russian text is allowed only in language data
    allowed = ("lang/", "text/", "readers/", "qa/", "voices/design.py", "book.py")
    bad = []
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if "vendor" in p.parts or rel.startswith(allowed):
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and re.search("[а-яА-ЯёЁ]{3}", node.value)):
                bad.append(f"{rel}: {node.value[:40]}")
    assert not bad, bad


def test_curly_apostrophe_stays_inside_words():
    from folivox import lang

    out = lang.get("en").normalize("I’m sure it’s John’s dog. He said “don’t go”, ‘really’.")
    assert out == "I'm sure it's John's dog. He said don't go, really."
    assert lang.get("fr").normalize("L’homme n’est pas là.").startswith("L'homme n'est")


def test_online_engines_keep_quotes_as_plain_marks():
    from folivox import lang
    from folivox.text.chunk import _keeping_quotes

    run = _keeping_quotes(lang.get("en").normalize)
    assert run("He said “don’t go”, and ‘really’ she asked.") == 'He said "don\'t go", and "really" she asked.'
    assert run("The dogs’ bowls.") == "The dogs bowls."  # no opening ‘: a closing ’ is not a quote
    ru = _keeping_quotes(lang.get("ru").normalize)
    assert ru("Он сказал «привет».") == 'Он сказал "привет".'
