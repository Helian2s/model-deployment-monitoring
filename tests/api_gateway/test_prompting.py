from app.models import ChatMessage
from app.prompting import messages_to_qwen_prompt, strip_echoed_prompt


def test_messages_to_qwen_prompt() -> None:
    prompt = messages_to_qwen_prompt(
        [
            ChatMessage(role="system", content="You are concise."),
            ChatMessage(role="user", content="Explain monitoring."),
        ]
    )

    assert "<|im_start|>system\nYou are concise.<|im_end|>" in prompt
    assert "<|im_start|>user\nExplain monitoring.<|im_end|>" in prompt
    assert prompt.endswith("<|im_start|>assistant\n")


def test_strip_echoed_prompt() -> None:
    prompt = "<|im_start|>user\nHello<|im_end|>\n<|im_start|>assistant\n"

    assert strip_echoed_prompt(f"{prompt}Hi there", prompt) == "Hi there"
    assert strip_echoed_prompt("Hi there", prompt) == "Hi there"
