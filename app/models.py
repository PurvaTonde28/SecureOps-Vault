from pydantic import BaseModel, field_validator


class GeneratedAnswer(BaseModel):
    """
    The exact shape we force the LLM's JSON output into.
    Field names here MUST match what we tell the model to return in the prompt —
    Pydantic doesn't know or care what the prompt says, it just validates
    whatever JSON comes back against this shape.
    """
    answer: str
    cited_chunk_indices: list[int]
    sufficient_context: bool

    @field_validator("cited_chunk_indices")
    @classmethod
    def indices_must_be_reasonable(cls, value: list[int]) -> list[int]:
        # Catches a model citing chunk 0 or chunk 47 when only 3 chunks existed —
        # a real failure mode, not a hypothetical one.
        for idx in value:
            if idx < 1:
                raise ValueError(f"chunk index {idx} is invalid — indices start at 1")
        return value


class GenerationResult(BaseModel):
    """
    What generate_answer() actually returns to the rest of the app — the
    validated answer, PLUS metadata Phase 7 (cost tracking) will need later.
    """
    model_config = {"protected_namespaces": ()}
    
    answer: str
    cited_chunk_ids: list[str]     # real UUIDs, resolved from cited_chunk_indices
    sufficient_context: bool
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    retries_used: int