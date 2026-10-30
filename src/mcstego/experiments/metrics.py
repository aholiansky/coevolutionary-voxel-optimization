from __future__ import annotations


def expected_post_embedding_prevalence(
    natural_prevalence: float,
    selection_rate: float,
    *,
    one_probability: float = 0.5,
) -> float:
    """Expected carrier-block prevalence after overwriting selected positions."""

    for name, value in (
        ("natural_prevalence", natural_prevalence),
        ("selection_rate", selection_rate),
        ("one_probability", one_probability),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0, 1]")
    return (1.0 - selection_rate) * natural_prevalence + selection_rate * one_probability

