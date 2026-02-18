"""
Optional Groq integration helpers.
"""

from __future__ import annotations

import json
import time
from typing import Optional, Any
from urllib import request, error

from ..settings import BackendSettings


class GroqAPIError(Exception):
    """Raised when a Groq API call fails or returns an invalid response."""


_GROQ_MODELS_CACHE: dict[str, Any] = {
    "api_key": None,
    "expires_at": 0.0,
    "models": [],
}


def _groq_headers(settings: BackendSettings) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        # Cloudflare can block default python-urllib user agents (error 1010).
        "User-Agent": "curl/8.5.0",
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.groq_api_key}",
    }


def list_available_groq_models(
    settings: BackendSettings,
    *,
    use_cache: bool = True,
    cache_ttl_seconds: int = 300,
) -> list[str]:
    """
    Return configured + remotely available Groq models.
    """
    configured_models = [m for m in settings.groq_models if m]
    if not settings.groq_api_key:
        return configured_models

    now = time.time()
    if (
        use_cache
        and _GROQ_MODELS_CACHE["api_key"] == settings.groq_api_key
        and now < _GROQ_MODELS_CACHE["expires_at"]
        and _GROQ_MODELS_CACHE["models"]
    ):
        return list(_GROQ_MODELS_CACHE["models"])

    remote_models: list[str] = []
    req = request.Request(
        url="https://api.groq.com/openai/v1/models",
        headers=_groq_headers(settings),
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=settings.groq_timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        data = body.get("data", [])
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    model_id = item.get("id")
                    if isinstance(model_id, str) and model_id.strip():
                        remote_models.append(model_id.strip())
    except Exception:
        # Keep resilient behavior: fallback to configured models only.
        remote_models = []

    merged: list[str] = []
    for model_id in [*configured_models, *remote_models]:
        if model_id not in merged:
            merged.append(model_id)

    _GROQ_MODELS_CACHE["api_key"] = settings.groq_api_key
    _GROQ_MODELS_CACHE["expires_at"] = now + max(30, cache_ttl_seconds)
    _GROQ_MODELS_CACHE["models"] = merged
    return merged


def call_groq_chat(
    settings: BackendSettings,
    *,
    messages: list[dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: int = 300,
    response_format: Optional[dict[str, str]] = None,
) -> str:
    """Call Groq chat API and return assistant content."""
    if not settings.groq_api_key:
        raise GroqAPIError("GROQ_API_KEY is not configured")

    target_model = model or settings.groq_model
    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    req = request.Request(
        url="https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_groq_headers(settings),
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=settings.groq_timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        try:
            response_body = e.read().decode("utf-8", errors="replace")
            parsed = json.loads(response_body)
            api_message = (
                parsed.get("error", {}).get("message")
                or parsed.get("message")
                or response_body[:300]
            )
        except Exception:
            api_message = str(e)
        hint = ""
        if e.code in (401, 403):
            hint = " Check GROQ_API_KEY, project permissions, and model access in Groq console."
        elif e.code == 429:
            hint = " Rate limit or quota exceeded; retry later or use another model."
        raise GroqAPIError(f"Groq API HTTP {e.code}: {api_message}.{hint}") from e
    except error.URLError as e:
        raise GroqAPIError(f"Groq API network error: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise GroqAPIError("Groq API returned invalid JSON payload") from e

    try:
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise GroqAPIError("Groq API returned empty content")
        return content.strip()
    except (KeyError, IndexError, TypeError) as e:
        raise GroqAPIError("Groq API response missing assistant content") from e


def _extract_json_payload(text: str) -> Optional[Any]:
    text = text.strip()
    if not text:
        return None

    # Try plain JSON first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try fenced code block JSON.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Some models return arrays directly.
    list_start = text.find("[")
    list_end = text.rfind("]")
    if list_start >= 0 and list_end > list_start:
        candidate = text[list_start : list_end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def compose_story_lines_with_groq(
    settings: BackendSettings,
    *,
    prompt: str,
    mode: str,
    language: str,
    characters: list[str],
    character_descriptions: Optional[dict[str, str]] = None,
    character_emotion_palettes: Optional[dict[str, list[str]]] = None,
    target_lines: int,
    model: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Compose a roleplay/novel script with explicit emotions.
    """
    char_list = ", ".join(characters)
    descriptions = character_descriptions or {}
    emotion_palettes = character_emotion_palettes or {}
    personality_lines = []
    for name in characters:
        desc = (descriptions.get(name) or "").strip()
        palette = [emotion for emotion in (emotion_palettes.get(name) or []) if emotion]
        palette_block = f" | allowed_emotions: {', '.join(palette)}" if palette else ""
        if desc:
            personality_lines.append(f"- {name}: {desc}{palette_block}")
        elif palette_block:
            personality_lines.append(f"- {name}:{palette_block}")
    personality_block = "\n".join(personality_lines) if personality_lines else "- (no personalities provided)"
    system = (
        "You create audio drama scripts. "
        "Return strict JSON only, no markdown, no extra text."
    )
    user = (
        f"Mode: {mode}\n"
        f"Language: {language}\n"
        f"Characters (must use only these names): {char_list}\n"
        f"Character personalities:\n{personality_block}\n"
        "IMPORTANT: For each line, emotion must be chosen from the character's allowed_emotions.\n"
        f"Target lines: {target_lines}\n"
        f"Prompt: {prompt}\n\n"
        "Output JSON schema:\n"
        "{\n"
        '  "lines": [\n'
        "    {\n"
        '      "character_name": "one of provided characters",\n'
        '      "text": "dialogue line",\n'
        '      "emotion": "neutral|happy|sad|angry|fearful|surprised|calm",\n'
        '      "emotion_intensity": 0.0-1.0\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )

    max_tokens = min(6000, max(1200, target_lines * 160))
    last_error = "Unknown Groq compose error"

    for attempt in range(2):
        extra = ""
        if attempt == 1:
            extra = (
                "\nIMPORTANT RETRY RULES:\n"
                "- Output must be valid JSON.\n"
                "- Keep each text line short (max 20 words).\n"
                "- Do not add explanations.\n"
            )

        content = call_groq_chat(
            settings,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"{user}{extra}"},
            ],
            model=model,
            temperature=0.3 if attempt == 0 else 0.2,
            max_tokens=max_tokens + (1000 if attempt == 1 else 0),
            response_format={"type": "json_object"},
        )

        parsed = _extract_json_payload(content)
        if parsed is None:
            preview = content[:240].replace("\n", " ")
            last_error = f"Groq returned non-JSON content: {preview}"
            continue

        lines: Any = None
        if isinstance(parsed, list):
            lines = parsed
        elif isinstance(parsed, dict):
            lines = parsed.get("lines") or parsed.get("script") or parsed.get("items")

        if not isinstance(lines, list):
            last_error = "Groq JSON does not contain a valid 'lines' array"
            continue

        normalized_lines = [line for line in lines if isinstance(line, dict)]
        if not normalized_lines:
            last_error = "Groq JSON 'lines' array is empty or invalid"
            continue

        return normalized_lines

    raise GroqAPIError(last_error)


def maybe_generate_emotion_instruction_with_groq(
    settings: BackendSettings,
    *,
    text: str,
    character_name: str,
    emotion: str,
    intensity: float,
    fallback_instruction: str,
    model: Optional[str] = None,
) -> str:
    """
    Returns an instruction string for TTS. Uses Groq only when configured.
    """
    if not settings.use_groq_instruct or not settings.groq_api_key:
        return fallback_instruction

    prompt = (
        "You write concise voice acting directions for TTS.\n"
        "Return ONLY one short sentence.\n"
        f"Character: {character_name}\n"
        f"Emotion: {emotion}\n"
        f"Intensity (0-1): {intensity:.2f}\n"
        f"Line: {text}\n"
    )

    try:
        content = call_groq_chat(
            settings,
            messages=[
                {"role": "system", "content": "You produce safe, concise TTS performance directions."},
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=0.4,
            max_tokens=80,
        )
        return content or fallback_instruction
    except GroqAPIError:
        return fallback_instruction
