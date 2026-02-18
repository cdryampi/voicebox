"""
Optional Groq integration helpers.
"""

from __future__ import annotations

import json
import time
from typing import Optional, Any
from urllib import request, error
import requests as http_requests

from ..settings import BackendSettings


class GroqAPIError(Exception):
    """Raised when a Groq API call fails or returns an invalid response."""


class GroqSTTError(Exception):
    """Raised for Groq STT (audio transcription) failures with stable error metadata."""

    def __init__(self, message: str, error_code: str, status_code: int = 503):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


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


def _extract_error_message(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
        msg = payload.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    return None


def transcribe_audio_with_groq(
    settings: BackendSettings,
    *,
    audio_path: str,
    language: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    Transcribe audio with Groq audio transcription API.
    """
    if not settings.groq_api_key:
        raise GroqSTTError(
            "Groq STT is not configured. Set VOICEBOX_GROQ_API_KEY (or GROQ_API_KEY).",
            error_code="STT_PROVIDER_NOT_CONFIGURED",
            status_code=503,
        )

    target_model = (model or settings.groq_stt_model or "whisper-large-v3-turbo").strip()
    if not target_model:
        raise GroqSTTError(
            "Groq STT model is not configured. Set VOICEBOX_GROQ_STT_MODEL.",
            error_code="STT_PROVIDER_NOT_CONFIGURED",
            status_code=503,
        )

    data: dict[str, str] = {
        "model": target_model,
        "response_format": "json",
    }
    if language:
        data["language"] = language

    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "User-Agent": "curl/8.5.0",
        "Accept": "application/json",
    }

    try:
        with open(audio_path, "rb") as fp:
            response = http_requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                data=data,
                files={"file": (audio_path.split("/")[-1], fp, "audio/wav")},
                timeout=settings.groq_timeout_seconds,
            )
    except http_requests.Timeout as e:
        raise GroqSTTError(
            "Groq STT timeout. Retry in a moment.",
            error_code="STT_PROVIDER_TIMEOUT",
            status_code=503,
        ) from e
    except http_requests.RequestException as e:
        raise GroqSTTError(
            f"Groq STT network error: {e}",
            error_code="STT_PROVIDER_NETWORK_ERROR",
            status_code=503,
        ) from e

    payload: Any
    try:
        payload = response.json()
    except Exception:
        payload = {"message": response.text[:400] if response.text else ""}

    if response.status_code == 429:
        message = _extract_error_message(payload) or "Groq STT rate limit exceeded."
        raise GroqSTTError(message, error_code="STT_PROVIDER_RATE_LIMIT", status_code=429)

    if response.status_code in {401, 403}:
        message = _extract_error_message(payload) or "Groq STT authentication failed."
        raise GroqSTTError(message, error_code="STT_PROVIDER_NOT_CONFIGURED", status_code=503)

    if response.status_code >= 400:
        message = _extract_error_message(payload) or f"Groq STT failed with HTTP {response.status_code}."
        raise GroqSTTError(message, error_code="STT_PROVIDER_ERROR", status_code=503)

    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise GroqSTTError(
            "Groq STT returned an empty transcription.",
            error_code="STT_PROVIDER_ERROR",
            status_code=503,
        )
    return text.strip()


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
    max_chars_per_line: Optional[int] = None,
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
    max_chars_limit = max(20, int(max_chars_per_line)) if max_chars_per_line is not None else None
    preferred_min_chars = max(24, int(max_chars_limit * 0.55)) if max_chars_limit else None
    max_chars_instruction = (
        f"Max chars per line: {max_chars_limit}\n"
        if max_chars_limit is not None
        else ""
    )
    pacing_instruction = (
        f"Preferred length per line: {preferred_min_chars}-{max_chars_limit} characters "
        "(avoid overly short one-liners unless intentional).\n"
        if max_chars_limit is not None and preferred_min_chars is not None
        else ""
    )
    user = (
        f"Mode: {mode}\n"
        f"Language: {language}\n"
        f"Characters (must use only these names): {char_list}\n"
        f"Character personalities:\n{personality_block}\n"
        "IMPORTANT: For each line, emotion must be chosen from the character's allowed_emotions.\n"
        f"Target lines: {target_lines}\n"
        f"{max_chars_instruction}"
        f"{pacing_instruction}"
        f"Prompt: {prompt}\n\n"
        "Quality requirements:\n"
        "- Each line must be a complete beat (1 to 3 sentences).\n"
        "- Keep dialogue concrete and scene-specific, avoid generic filler.\n"
        "- Respect language and mode exactly.\n\n"
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

    max_tokens = min(7000, max(1600, target_lines * 240))
    last_error = "Unknown Groq compose error"
    retry_feedback = ""
    min_required_lines = max(2, int(target_lines * 0.7))

    for attempt in range(3):
        extra = ""
        if attempt > 0:
            retry_line_rule = (
                f"- Keep every text line <= {max_chars_limit} characters.\n"
                if max_chars_limit is not None
                else ""
            )
            extra = (
                "\nIMPORTANT RETRY RULES:\n"
                "- Output must be valid JSON.\n"
                f"{retry_line_rule}"
                "- Return a `lines` array with enough entries to match target_lines.\n"
                "- Do not add explanations.\n"
            )
            if retry_feedback:
                extra += f"\nPrevious output issues to fix:\n{retry_feedback}\n"

        content = call_groq_chat(
            settings,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"{user}{extra}"},
            ],
            model=model,
            temperature=0.3 if attempt == 0 else 0.18,
            max_tokens=max_tokens + (1000 if attempt > 0 else 0),
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

        normalized_lines = [
            line
            for line in lines
            if isinstance(line, dict) and str(line.get("text", "")).strip()
        ]
        if not normalized_lines:
            last_error = "Groq JSON 'lines' array is empty or invalid"
            continue

        if len(normalized_lines) < min_required_lines:
            last_error = (
                f"Groq returned too few lines ({len(normalized_lines)} < {min_required_lines})"
            )
            retry_feedback = last_error
            continue

        if max_chars_limit is not None:
            too_long: list[str] = []
            too_short: list[str] = []
            for idx, line in enumerate(normalized_lines):
                text_value = str(line.get("text", "")).strip()
                text_len = len(text_value)
                if text_len > max_chars_limit:
                    too_long.append(f"#{idx + 1}={text_len}")
                elif preferred_min_chars is not None and text_len < preferred_min_chars:
                    too_short.append(f"#{idx + 1}={text_len}")

            if too_long:
                sample = ", ".join(too_long[:6])
                last_error = f"Groq returned lines above max chars ({sample})"
                retry_feedback = (
                    f"Some lines exceeded max chars {max_chars_limit}: {sample}. "
                    "Rewrite those lines to fit without losing meaning."
                )
                continue

            if len(too_short) > max(2, int(len(normalized_lines) * 0.6)):
                sample = ", ".join(too_short[:6])
                last_error = "Groq returned too many short lines for the configured char budget"
                retry_feedback = (
                    f"Too many lines were shorter than {preferred_min_chars} chars: {sample}. "
                    "Expand lines with richer, scene-specific detail."
                )
                continue

        return normalized_lines

    raise GroqAPIError(last_error)


def compose_studio_director_suggestions_with_groq(
    settings: BackendSettings,
    *,
    character_description: str,
    story_name_hint: Optional[str],
    mode: str,
    language: str,
    target_cards: int,
    max_chars_per_card: int,
    model: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Build four short Story Director presets from a single character description.
    """
    system = (
        "You are a story director assistant for voice roleplay workflows. "
        "Return strict JSON only with exactly four distinct ideas."
    )
    user = (
        f"Character description:\n{character_description.strip()}\n\n"
        f"Story name hint: {(story_name_hint or '').strip() or '(none)'}\n"
        f"Mode: {mode}\n"
        f"Language: {language}\n"
        f"Target cards: {target_cards}\n\n"
        f"Max chars per card: {max(20, int(max_chars_per_card))}\n\n"
        "Create 4 different short-story presets. Keep them practical for TTS card generation.\n"
        "Each preset must include:\n"
        "- title\n"
        "- description\n"
        "- prompt (specific, production-ready, with constraints)\n"
        "- limits object with max_lines, max_chars_per_line, preview_seconds\n"
        "- protagonist_name and narrator_name\n"
        "- protagonist_description and narrator_description\n"
        "- preview_outline (2 to 4 bullets)\n\n"
        "Prompt quality rules:\n"
        "- Must explicitly mention emotional arc and scene progression.\n"
        "- Must include hard constraints for cards count and max chars/card.\n"
        "- Must avoid vague instructions like 'be creative'.\n\n"
        "Output JSON schema:\n"
        "{\n"
        '  "suggestions": [\n'
        "    {\n"
        '      "title": "short title",\n'
        '      "description": "short summary",\n'
        '      "prompt": "director prompt for generating cards",\n'
        '      "limits": {"max_lines": 8, "max_chars_per_line": 300, "preview_seconds": 5},\n'
        '      "protagonist_name": "Protagonista",\n'
        '      "narrator_name": "Narrador",\n'
        '      "protagonist_description": "personality and speaking style",\n'
        '      "narrator_description": "narration style",\n'
        '      "preview_outline": ["bullet 1", "bullet 2"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )

    max_tokens = 2400
    last_error = "Unknown Groq suggestions error"

    for attempt in range(2):
        retry_extra = ""
        if attempt == 1:
            retry_extra = (
                "\nIMPORTANT RETRY RULES:\n"
                "- Return valid JSON object.\n"
                "- Include exactly 4 suggestions.\n"
                "- Keep preview_outline between 2 and 4 bullets.\n"
            )

        content = call_groq_chat(
            settings,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"{user}{retry_extra}"},
            ],
            model=model,
            temperature=0.45 if attempt == 0 else 0.3,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        parsed = _extract_json_payload(content)
        if not isinstance(parsed, dict):
            last_error = "Groq suggestions response is not a JSON object"
            continue

        raw_suggestions = parsed.get("suggestions") or parsed.get("ideas") or parsed.get("items")
        if not isinstance(raw_suggestions, list):
            last_error = "Groq suggestions JSON does not include a valid suggestions array"
            continue

        normalized: list[dict[str, Any]] = []
        for raw in raw_suggestions:
            if not isinstance(raw, dict):
                continue

            title = str(raw.get("title", "")).strip()
            prompt = str(raw.get("prompt", "")).strip()
            description = str(raw.get("description", "")).strip()[:500] or None
            outline_raw = raw.get("preview_outline") or raw.get("outline") or []

            outline: list[str] = []
            if isinstance(outline_raw, list):
                for item in outline_raw:
                    text = str(item).strip()
                    if text:
                        outline.append(text[:180])
            elif isinstance(outline_raw, str):
                for chunk in outline_raw.split("\n"):
                    text = chunk.strip("-* ").strip()
                    if text:
                        outline.append(text[:180])

            if len(outline) < 2:
                seed = description or prompt
                fragments = [part.strip() for part in seed.split(".") if part.strip()]
                outline = fragments[:2]
            outline = outline[:4]

            if not title or not prompt or len(outline) < 2:
                continue

            normalized.append(
                {
                    "title": title[:100],
                    "description": description,
                    "prompt": prompt[:4000],
                    "limits": raw.get("limits"),
                    "protagonist_name": str(raw.get("protagonist_name", "")).strip()[:100],
                    "narrator_name": str(raw.get("narrator_name", "")).strip()[:100],
                    "protagonist_description": str(
                        raw.get("protagonist_description", "")
                    ).strip()[:500],
                    "narrator_description": str(raw.get("narrator_description", "")).strip()[:500],
                    "preview_outline": outline,
                }
            )

        if len(normalized) >= 4:
            return normalized[:4]

        last_error = f"Groq returned {len(normalized)} valid suggestions (expected 4)"

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
