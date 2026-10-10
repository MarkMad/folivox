import typer.main
from typer.testing import CliRunner

from folivox.cli import app
from folivox.helptext import TOPICS

runner = CliRunner()


def test_no_args_prints_quick_start():
    r = runner.invoke(app, [])
    assert r.exit_code == 0
    assert "Quick start" in r.output and "folivox help" in r.output


def test_every_render_option_is_documented_and_grouped():
    cmd = typer.main.get_command(app).commands["render"]
    for p in cmd.params:
        if p.name == "help":
            continue
        assert getattr(p, "help", None) or p.param_type_name == "argument", p.name
        if p.param_type_name == "option":
            assert p.rich_help_panel, f"{p.name} has no help panel"


def test_help_topics():
    for name in TOPICS:
        r = runner.invoke(app, ["help", name])
        assert r.exit_code == 0 and TOPICS[name][0] in r.output
    assert runner.invoke(app, ["help", "nope"]).exit_code == 2
    assert runner.invoke(app, ["help"]).exit_code == 0


def test_epilogs_show_examples():
    assert "Examples" in runner.invoke(app, ["--help"]).output
    assert "Examples" in runner.invoke(app, ["render", "--help"]).output
