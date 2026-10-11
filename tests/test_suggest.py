import pytest

from folivox.voices.suggest import suggest_design_prompt


class FakeLLM:
    name = "fake"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, prompt, system=None, temperature=0.3):
        self.prompts.append((prompt, system))
        return self.reply


def test_prompt_uses_book_and_cleans_reply():
    llm = FakeLLM('```\nVoice description: "A calm older man with a low, gravelly timbre, slow pace, warm and '
                  'wistful; suits a quiet Victorian ghost story."\n```')
    out = suggest_design_prompt("Fog crept over the moor. " * 50, "en", llm, title="The Moor", author="A. Writer")
    assert out.startswith("A calm older man") and "```" not in out and not out.endswith('"')
    prompt, system = llm.prompts[0]
    assert "The Moor by A. Writer" in prompt and "Fog crept" in prompt and "real person" in system


def test_long_reply_is_cut_at_a_sentence():
    out = suggest_design_prompt("text " * 100, "en", FakeLLM("A warm voice. " * 80), max_chars=100)
    assert len(out) <= 100 and out.endswith(".")


@pytest.mark.parametrize("reply", ["", "ok", "Sounds like a famous actor reading slowly and calmly."])
def test_unusable_reply(reply):
    with pytest.raises(ValueError):
        suggest_design_prompt("text " * 100, "en", FakeLLM(reply))


def test_book_passages_are_about_ten_seconds_and_without_lists():
    from folivox.voices.design import char_range, is_safe

    lo, hi = char_range("ru")
    assert (lo, hi) == (90, 150) and char_range("zh")[1] < 70  # character scripts are shorter per second
    ok = "Утром над рекой поднялся лёгкий туман. Старый мост медленно выступал из белой дымки, и стало тихо."
    assert lo <= len(ok) <= hi and is_safe(ok, "ru")
    assert not is_safe(ok + " Потом наступил вечер, и тёплый свет лёг на воду и на дальний берег.", "ru")  # too long
    assert not is_safe("Проверка укладки камня/плитки. Проверка расположения потолочных карнизов в доме.", "ru")
