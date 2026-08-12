import os
import json
import logging
from groq import Groq
from pydantic import ValidationError
from app.models import GeneratedAnswer, GenerationResult

logger = logging.getLogger(__name__)

_groq_client = None


def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


def build_context_block(chunks: list[dict]) -> str:
    """
    Numbers each chunk [1], [2], [3]... so the model can cite by small integer
    instead of needing to reproduce a real UUID (see Decision 2 above).
    """
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(f"[{i}] {chunk['content']}")
    return "\n\n".join(lines)


def build_system_prompt() -> str:
    return (
        "You are a secure internal knowledge assistant. Answer the user's question "
        "using ONLY the numbered context blocks provided. Do not use outside knowledge.\n\n"
        "Always answer in one or more complete, clear sentences that would make sense "
        "to someone who hasn't seen the context — do not answer with a bare term, "
        "fragment, or keyword.\n\n"
        "Respond with ONLY a JSON object, no other text, matching exactly this shape:\n"
        '{"answer": "...", "cited_chunk_indices": [1, 2], "sufficient_context": true}\n\n'
        "- cited_chunk_indices must list the numbers of context blocks you actually used.\n"
        "- If the context does not contain enough information to answer, set "
        'sufficient_context to false, set cited_chunk_indices to [], and explain '
        "in 'answer' that the available context is insufficient."
    )


def _call_groq(messages: list[dict]) -> tuple[str, dict]:
    client = get_groq_client()
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        response_format={"type": "json_object"},  # Groq's own JSON-mode safety net,
                                                     # on top of our Pydantic validation
        temperature=0.1,  # low temperature: we want consistent, grounded answers,
                           # not creative variation, for a factual QA system
    )
    raw_text = response.choices[0].message.content
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }
    return raw_text, usage


def generate_answer(query: str, chunks: list[dict], max_retries: int = 2) -> GenerationResult:
    """
    chunks: the top_n results from rerank() in Phase 5. Each dict has 'id' (real UUID)
    and 'content'.
    """
    context_block = build_context_block(chunks)
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": f"CONTEXT:\n{context_block}\n\nQUESTION:\n{query}"},
    ]

    last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    for attempt in range(max_retries + 1):
        raw_text, usage = _call_groq(messages)
        last_usage = usage

        try:
            parsed_json = json.loads(raw_text)
            validated = GeneratedAnswer(**parsed_json)

            # Extra safety: a cited index bigger than how many chunks we actually sent
            # is a still a failure even though it passed the >=1 check in models.py.
            if any(idx > len(chunks) for idx in validated.cited_chunk_indices):
                raise ValueError("cited index exceeds number of provided chunks")

            cited_chunk_ids = [chunks[idx - 1]["id"] for idx in validated.cited_chunk_indices]

            return GenerationResult(
                answer=validated.answer,
                cited_chunk_ids=cited_chunk_ids,
                sufficient_context=validated.sufficient_context,
                model_used="llama-3.1-8b-instant",
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                retries_used=attempt,
            )

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning(f"generation attempt {attempt} failed validation: {e}")
            if attempt < max_retries:
                # Give the model its own bad output back, and ask it to fix it —
                # more effective than repeating the original instructions verbatim.
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({
                    "role": "user",
                    "content": f"That was not valid JSON matching the required schema ({e}). "
                                f"Return ONLY the corrected JSON object, nothing else.",
                })

    # Every attempt failed — fail loudly, not silently (see Decision 4).
    logger.error(f"generation failed after {max_retries + 1} attempts for query: {query}")
    raise RuntimeError(f"Failed to get valid structured output after {max_retries + 1} attempts")


def judge_answer(query: str, expected_answer: str, actual_answer: str, actual_sufficient: bool, expect_sufficient: bool) -> dict:
    """
    An intentionally separate, simply-worded prompt — not reusing generate_answer()'s
    schema or system prompt, so a bug there can't make the judge agree with it blindly.
    """
    client = get_groq_client()
    judge_prompt = (
        f"You are evaluating an AI system's answer for correctness.\n\n"
        f"Question: {query}\n"
        f"Expected answer (reference): {expected_answer}\n"
        f"Actual answer given: {actual_answer}\n\n"
        f"Does the actual answer convey the same core information as the expected answer? "
        f"Minor phrasing differences are fine. Respond with ONLY JSON: "
        f'{{"correct": true or false, "reasoning": "one sentence why"}}'
    )

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": judge_prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,  # judge should be as deterministic as possible
    )

    verdict = json.loads(response.choices[0].message.content)
    context_match = actual_sufficient == expect_sufficient

    return {
        "content_correct": verdict.get("correct", False),
        "reasoning": verdict.get("reasoning", ""),
        "context_flag_correct": context_match,
        "passed": verdict.get("correct", False) and context_match,
    }