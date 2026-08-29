from __future__ import annotations

from langparse.workbooks.modeling.pricing import calculate_cost_usd


def test_calculate_cost_usd():
    # Rates come from the deployment contract, not a model-name lookup.
    cost = calculate_cost_usd(
        prompt_tokens=10000,
        completion_tokens=2000,
        input_cost_usd_per_million=1.25,
        output_cost_usd_per_million=5.0,
    )
    assert abs(cost - 0.0225) < 1e-6


def test_calculate_cost_zero_tokens():
    cost = calculate_cost_usd(
        prompt_tokens=0,
        completion_tokens=0,
        input_cost_usd_per_million=1.25,
        output_cost_usd_per_million=5.0,
    )
    assert cost == 0.0
