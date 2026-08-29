from __future__ import annotations


def calculate_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    input_cost_usd_per_million: float,
    output_cost_usd_per_million: float,
) -> float:
    """Calculate observed cost using deployment-supplied, versioned policy rates."""
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0.0

    prompt_cost = (prompt_tokens / 1_000_000.0) * input_cost_usd_per_million
    completion_cost = (completion_tokens / 1_000_000.0) * output_cost_usd_per_million
    return prompt_cost + completion_cost
