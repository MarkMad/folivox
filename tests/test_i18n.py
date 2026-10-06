import ast
import re
import string
from pathlib import Path

import pytest

from folivox import i18n
from folivox.locales import ru

SRC = Path(__file__).parent.parent / "src" / "folivox"


def _messages() -> set[str]:
    out = set()
    for p in SRC.rglob("*.py"):
        if "vendor" in p.parts:
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                out.add(node.args[0].value)
    return out


def _fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


@pytest.mark.parametrize("catalog", [ru.MESSAGES], ids=["ru"])
def test_catalog_complete_and_consistent(catalog):
    msgs = _messages()
    missing = sorted(msgs - set(catalog))
    assert not missing, f"untranslated: {missing}"
    stale = sorted(set(catalog) - msgs)
    assert not stale, f"unused: {stale}"
    for en, tr in catalog.items():
        assert _fields(en) == _fields(tr), en


def test_source_has_no_hardcoded_russian_messages():
    # user-facing strings must go through _(); Russian text is only allowed in language data
    allowed = ("lang/", "locales/", "text/", "readers/", "qa/", "voices/design.py", "book.py")
    bad = []
    msgs = _messages()
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if "vendor" in p.parts or rel.startswith(allowed):
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in msgs
                    and re.search("[а-яА-ЯёЁ]{3}", node.value)):
                bad.append(f"{rel}: {node.value[:40]}")
    assert not bad, bad


def test_ui_lang_switch(monkeypatch):
    monkeypatch.setenv("FOLIVOX_UI_LANG", "ru")
    i18n.ui_lang.cache_clear()
    assert i18n._("Voices") == "Голоса"
    assert i18n._("Removed {id}", id="x") == "Удалён x"
    monkeypatch.setenv("FOLIVOX_UI_LANG", "en")
    i18n.ui_lang.cache_clear()
    assert i18n._("Voices") == "Voices"
    i18n.ui_lang.cache_clear()
