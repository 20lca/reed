from __future__ import annotations

from datetime import date


EXPLANATORY_STATEMENT = (
    "Product Carbon Footprint associated with the cradle-to-gate life cycle phases "
    "(A1-A3) of the product, calculated using the specific production data provided "
    "by the company for this product."
)


def make_dpp_output(
    *,
    company: str,
    event_id: str,
    product: str,
    country: str,
    publication_date: date,
    score_a1: float,
    score_a2: float,
    score_a3: float,
) -> dict[str, object]:
    def make_pcf_entry(score: float, phase: str) -> dict[str, object]:
        return {
            "PcfCalculationMethods": [{"PcfCalculationMethod": "ISO 14044"}],
            "PCF in kg CO2eq": round(score, 1),
            "ProcessName": f"{product} {phase}",
            "ReferenceValueForCalculation": "unit",
            "QuantityOfMeasureForCalculation": 1,
            "LifeCyclePhases": [{"LifeCyclePhase": phase}],
            "ExplanatoryStatement": EXPLANATORY_STATEMENT,
            "GoodsHandoverAddress": {"Country": country},
            "PublicationDate": publication_date.isoformat(),
        }

    return {
        "DPP": [
            {
                "company": company,
                "event_id": event_id,
                "product": product,
                "carbonFootprint": {
                    "ProductCarbonFootprints": [
                        make_pcf_entry(score_a1, "A1"),
                        make_pcf_entry(score_a2, "A2"),
                        make_pcf_entry(score_a3, "A3"),
                        make_pcf_entry(score_a1 + score_a2 + score_a3, "A1-A3"),
                    ]
                },
            }
        ]
    }
