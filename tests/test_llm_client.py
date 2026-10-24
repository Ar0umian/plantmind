import os
from types import SimpleNamespace as NS

os.environ["MOCK_LLM"] = "1"

from core.llm_client import LLMClient, LLMError


class _FakeClient:
    """Records the arguments of every call; optionally rejects extra_body once (HTTP 400)."""

    def __init__(self, reject_extra=False, fail_always=False):
        self.calls, self.reject_extra, self.fail_always = [], reject_extra, fail_always
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_always:
            raise RuntimeError("network down")
        if self.reject_extra and "extra_body" in kwargs:
            error = RuntimeError("unknown field")
            error.status_code = 400
            raise error
        message = NS(content='{"ok": true}')
        return NS(choices=[NS(message=message)], usage=NS(prompt_tokens=5, completion_tokens=3))


def _client(no_think="nano", **fake_options):
    old = {k: os.environ.get(k) for k in ("NO_THINK_TIERS", "MODEL_NANO", "MODEL_SUPER", "MODEL_ULTRA")}
    os.environ.update({"MODEL_NANO": "m-nano", "MODEL_SUPER": "m-super", "MODEL_ULTRA": "m-ultra",
                       "NO_THINK_TIERS": no_think})
    try:
        client = LLMClient()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    fake = _FakeClient(**fake_options)
    client._client = fake
    return client, fake


def test_thinking_is_switched_off_only_for_the_configured_tiers():
    client, fake = _client("nano")
    client._chat("nano", "s", "u")
    client._chat("super", "s", "u")
    assert fake.calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "extra_body" not in fake.calls[1]


def test_no_tiers_configured_means_the_option_is_never_sent():
    client, fake = _client("")
    client._chat("nano", "s", "u")
    assert "extra_body" not in fake.calls[0]


def test_several_tiers_can_be_configured():
    client, fake = _client("nano, super")
    client._chat("super", "s", "u")
    client._chat("ultra", "s", "u")
    assert "extra_body" in fake.calls[0] and "extra_body" not in fake.calls[1]


def test_a_model_that_rejects_the_option_is_retried_without_it_and_remembered():
    client, fake = _client("nano", reject_extra=True)
    assert client._chat("nano", "s", "u") == '{"ok": true}'
    assert "extra_body" in fake.calls[0] and "extra_body" not in fake.calls[1]
    client._chat("nano", "s", "u")
    assert "extra_body" not in fake.calls[2]            # not sent again
    assert client.usage[-1]["completion_tokens"] == 3


def test_other_errors_are_still_retried_then_reported():
    import time
    original = time.sleep
    time.sleep = lambda seconds: None                  # keep the test fast
    try:
        client, fake = _client("nano", fail_always=True)
        try:
            client._chat("nano", "s", "u")
            assert False, "must raise"
        except LLMError as exc:
            assert "network down" in str(exc)
        assert len(fake.calls) == 3
    finally:
        time.sleep = original
