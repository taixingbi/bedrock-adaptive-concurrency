from __future__ import annotations

WORKLOADS = {
    "short": {"input_tokens": 512, "max_tokens": 128},
    "long": {"input_tokens": 4096, "max_tokens": 512},
}

_FILLER = "lorem ipsum dolor sit amet consectetur adipiscing elit "


def build_prompt(input_tokens: int, max_tokens: int) -> str:
    instruction = (
        f"Ignore the filler text after the blank line. Write a single coherent "
        f"passage of about {max_tokens} tokens and then stop.\n\n"
    )
    remaining = max(input_tokens - max(len(instruction) // 4, 1), 0)
    words = _FILLER.split()
    filler_words = [words[i % len(words)] for i in range(remaining)]
    return instruction + " ".join(filler_words)


def resolve_workload(prompt_class: str | None, input_tokens: int | None, max_tokens: int | None) -> tuple[int, int, str]:
    preset = WORKLOADS.get(prompt_class or "")
    if preset:
        inp = int(input_tokens or preset["input_tokens"])
        out = int(max_tokens or preset["max_tokens"])
        return inp, out, prompt_class or "custom"
    return int(input_tokens or 512), int(max_tokens or 128), prompt_class or "custom"
