import os

import pytest

from chat_google.chat_service import chat


@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_live_query_without_ui():
    if os.getenv("RUN_LIVE_SMOKE", "0") != "1":
        pytest.skip("Set RUN_LIVE_SMOKE=1 to enable live smoke query test.")

    model_name = (os.getenv("SMOKE_MODEL") or os.getenv("MODEL") or "").strip()
    prompt = (
        os.getenv("SMOKE_PROMPT")
        or "find recent emails from social school, summarize"
    ).strip()

    if not model_name:
        pytest.skip("MODEL or SMOKE_MODEL is required for live smoke test.")

    if model_name.startswith("gemini"):
        if not os.getenv("GOOGLE_GEMINI_API_KEY"):
            pytest.skip("GOOGLE_GEMINI_API_KEY is required for Gemini live smoke test.")
    else:
        if not os.getenv("API_KEY") or not os.getenv("BASE_URL"):
            pytest.skip("API_KEY and BASE_URL are required for non-Gemini live smoke test.")

    outputs = []
    async for updated_history in chat(prompt, [], model_name):
        outputs.append(updated_history)

    assert outputs, "Chat produced no output."
    final_text = outputs[-1][-1].get("content", "").strip()
    assert final_text, "Final response is empty."
    assert not final_text.lower().startswith("error:"), final_text
