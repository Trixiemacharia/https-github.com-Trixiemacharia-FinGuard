import json
from urllib.request import Request, urlopen

from django.conf import settings


class LanguageProviderUnavailable(Exception):
    pass


def phrase_answer(question, deterministic_answer, tool_data):
    """Optional language-only provider. It receives calculated facts, never executes tools."""
    if settings.ASSISTANT_LLM_PROVIDER != "openai" or not settings.OPENAI_API_KEY:
        raise LanguageProviderUnavailable("Language provider is not configured.")
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "You are a language layer for a wallet assistant. Rewrite the supplied deterministic answer in clear, concise language. Do not calculate, infer, or add facts. Use only facts present in the supplied answer and tool data. Do not propose or perform financial actions."},
            {"role": "user", "content": json.dumps({"question": question, "answer": deterministic_answer, "tool_data": tool_data}, default=str)},
        ],
        "temperature": 0,
        "max_tokens": 180,
    }
    request = Request(
        settings.OPENAI_API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            content = json.loads(response.read()).get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as exc:
        raise LanguageProviderUnavailable("Language provider request failed.") from exc
    if not isinstance(content, str) or not content.strip():
        raise LanguageProviderUnavailable("Language provider returned no answer.")
    return content.strip()
