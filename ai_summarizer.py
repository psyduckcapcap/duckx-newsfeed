"""
DuckX Newsfeed - AI Summarizer
===============================
Uses the official Google GenAI SDK (google-genai >= 1.70, Python 3.12+).
Supports 4 Gemini models (3 free + 1 paid), each with separate API key.
Model: gemini-3-flash-preview (Free tier, default thinking = "high")

Optimized for Gemini 3 API:
  - Không cần truyền thinking_config — default đã là "high" dynamic thinking
  - Temperature giữ mặc định 1.0 (Gemini 3 khuyến nghị, tránh lặp/giảm chất lượng)
  - Cache client theo API key để tránh tạo lại mỗi request
"""

import os
from google import genai
from config_manager import AI_MODELS

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-31b-it")
MAX_TWEETS_INPUT_CHARS = 100_000  # ~25k tokens; Gemini 3 Flash supports 1M but cost/latency scales

# Cache client instances by API key — tránh tạo lại mỗi request
_client_cache: dict[str, genai.Client] = {}


def _get_client(api_key: str) -> genai.Client:
    """Get or create a cached GenAI client for the given API key."""
    if api_key not in _client_cache:
        _client_cache[api_key] = genai.Client(api_key=api_key)
    return _client_cache[api_key]


def _get_api_key(model_id: str) -> str:
    """Get API key for a specific model from .env"""
    model_info = AI_MODELS.get(model_id)
    if not model_info:
        return ""
    return os.getenv(model_info["env_key"], "")


def summarize_with_gemini(tweets_text: str, prompt: str, api_key: str) -> str:
    """
    Summarize tweets using Google GenAI SDK (Gemini 3 Flash Preview).

    Tối ưu theo Gemini 3 docs:
      - thinking: không set thinking_config → Gemini 3 Flash mặc định dùng "high" (dynamic)
      - max_output_tokens: không set → dùng mặc định của Gemini (64k tokens)
      - temperature: không set → mặc định 1.0 (Gemini 3 khuyến nghị)
      - tools: không set → free tier chỉ hỗ trợ text
    """
    if not api_key:
        return "[ERROR] API Key chua duoc cau hinh cho model nay"

    try:
        client = _get_client(api_key)

        if len(tweets_text) > MAX_TWEETS_INPUT_CHARS:
            tweets_text = tweets_text[:MAX_TWEETS_INPUT_CHARS]

        full_prompt = f"{prompt}\n\n--- TWEETS ---\n{tweets_text}"

        # Không cần truyền thinking_config — Gemini 3 Flash mặc định dùng "high" thinking
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=full_prompt,
        )

        if response.text:
            return response.text
        return "[ERROR] Gemini tra ve response rong"

    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "quota" in err_msg.lower():
            return (
                f"[ERROR] Gemini het quota hoac rate limit. "
                f"Kiem tra tai: https://aistudio.google.com/apikey "
                f"hoac doi sang model/key khac. ({err_msg[:150]})"
            )
        return f"[ERROR] Gemini exception: {err_msg[:200]}"


def summarize_tweets(tweets_text: str, prompt: str, model_id: str = "gemini_free_1") -> str:
    """
    Summarize tweets using the specified AI model.

    Args:
        tweets_text: Tweet content as text
        prompt: System prompt for summarization
        model_id: One of gemini_free_1, gemini_free_2, gemini_free_3, gemini_paid_1
    """
    if not tweets_text.strip():
        return "Khong co tweets moi de tom tat."

    api_key = _get_api_key(model_id)
    return summarize_with_gemini(tweets_text, prompt, api_key)
