"""Static checks for the Windows installer (no PowerShell needed)."""

import re
from pathlib import Path

PS1 = Path(__file__).resolve().parents[1] / "scripts" / "install.ps1"


def _code_lines():
    """Lines with strings and # comments removed (rough PowerShell lexer, enough for this script)."""
    text = PS1.read_text(encoding="ascii")
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        line = re.sub(r"'[^']*'", "''", line)
        line = re.sub(r'"(?:`.|[^"`])*"', '""', line)
        out.append(line.split("#", 1)[0])
    return out


def test_pure_ascii_without_bom():
    # PS 5.1 reads a BOM-less file as ANSI; a BOM can break `irm | iex`. ASCII works for both.
    raw = PS1.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    raw.decode("ascii")


def test_no_powershell7_only_syntax():
    for n, line in enumerate(_code_lines(), 1):
        for tok in ("??", "&&", "||", "?."):
            assert tok not in line, f"line {n}: {tok} is PowerShell 7 only"
        assert not re.search(r"\s\?\s.*\s:\s", line), f"line {n}: ternary is PowerShell 7 only"


def test_braces_and_parens_balanced():
    # A trailing comment once swallowed a closing brace and broke parsing of the whole script.
    code = "\n".join(_code_lines())
    assert code.count("{") == code.count("}")
    assert code.count("(") == code.count(")")


def test_cyrillic_answers_built_from_char_codes():
    text = PS1.read_text(encoding="ascii")
    assert "[char]0x434" in text and "[char]0x43D" in text
    assert "Tls12" in text


def test_failed_setup_stops_before_studio_offer():
    text = PS1.read_text(encoding="ascii")
    setup = text.index("folivox setup --skip-models")
    check = text.index("if ($LASTEXITCODE -ne 0) { Die", setup)
    assert check < text.index("Start the studio now?")
    assert "folivox doctor" in text[check : check + 400]
