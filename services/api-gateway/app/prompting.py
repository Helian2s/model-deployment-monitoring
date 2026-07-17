from __future__ import annotations

from .models import ChatMessage


def messages_to_qwen_prompt(messages: list[ChatMessage]) -> str:
    """Build the ChatML-style prompt Qwen2.5 Instruct expects."""
    parts: list[str] = []
    for message in messages:
        content = message.content.strip()
        if not content:
            continue
        parts.append(f"<|im_start|>{message.role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def strip_echoed_prompt(generated_text: str, prompt: str) -> str:
    if generated_text.startswith(prompt):
        return generated_text[len(prompt) :].lstrip()
    return generated_text.strip()


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    # Conservative fallback when Triton does not return token counts.
    return max(1, len(text) // 4)
