from __future__ import annotations


def make_simulation_output(
    *,
    product: str,
    score_a1: float,
    score_a2: float,
    score_a3: float,
    machining_contributions: list[dict[str, object]],
) -> dict[str, object]:
    operations = [
        {
            "operation": str(item["operation"]),
            "amount": round(float(item["amount"]), 6),
        }
        for item in machining_contributions
    ]

    return {
        "product": product,
        "total_climate_impact_kg_co2eq": round(score_a1 + score_a2 + score_a3, 4),
        "a1_raw_materials": {
            "total_kg_co2eq": round(score_a1, 4),
        },
        "a2_transport": {
            "total_kg_co2eq": round(score_a2, 4),
        },
        "a3_machining": {
            "total_kg_co2eq": round(sum(item["amount"] for item in operations), 4),
            "operations": operations,
        },
    }
