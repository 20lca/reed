from __future__ import annotations


def make_monitoring_output(
    *,
    product: str,
    total_climate_impact: float,
    machining_contributions: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "product": product,
        "total_climate_impact_kg_co2eq": round(total_climate_impact, 4),
        "machining_contributions": [
            {
                "operation": str(item["operation"]),
                "amount": round(float(item["amount"]), 6),
            }
            for item in machining_contributions
        ],
    }
