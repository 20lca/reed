import pandas as pd
import bw2analyzer as bwa
from datetime import date
import json

from reed.serializers.dpp import make_dpp_output

def lca_score(process_dict:dict, method:tuple)->pd.DataFrame:
    """_summary_

    Args:
        process_dict (dict): _description_
        method (tuple): _description_

    Returns:
        pd.DataFrame: _description_
    """
    #TODO: optimize, for example, re-using the LCA object

    results = []
    for name, process in process_dict.items():
        lca = process.lca(method)
        results.append({
            "Process": name,
            "Location": process.get('location'),
            "Functional Unit": process.get('unit'),
            "Climate Impact (kg CO2eq)": lca.score
        })

    return pd.DataFrame(results)

def lca_score2(demand,lcia_method):

    lca_exists = False
    results = []
    # TODO we don't need the name of the activity in the dict. we use directly
    # the activity name
    for process in demand.values():

        if not lca_exists:
            lca = process.lca(lcia_method)
            lca_exists = True
        else:
            lca.redo_lcia({process.id:1})

        results.append({
            "Process": process["name"],
            "Location": process.get('location'),
            "Functional Unit": process.get('unit'),
            "Climate Impact (kg CO2eq)": lca.score
        })
    return pd.DataFrame(results)

def run_contribution_analysis(demand_object,
                              lcia_method,
                              max_level=1,
                              cutoff=0.01):
    return bwa.utils.recursive_calculation_to_object(
        demand_object,
        lcia_method=lcia_method,
        max_level=max_level,
        cutoff=cutoff,
        as_dataframe=True,
    )

def get_machining_activity(total_activity):
    # First, search direct exchanges
    for exchange in total_activity.exchanges():
        linked = exchange.input
        if "soraluce machining" in linked["name"].lower():
            return linked

    # If not found, search one level deeper through sub-activities
    for exchange in total_activity.exchanges():
        linked = exchange.input
        try:
            for sub_exchange in linked.exchanges():
                sub_linked = sub_exchange.input
                if "soraluce machining" in sub_linked["name"].lower():
                    return sub_linked
        except Exception:
            continue  # skip exchanges that aren't activities (e.g. biosphere)

    raise ValueError(
        f"No Soraluce machining activity found in exchanges of '{total_activity['name']}' "
        f"or its direct sub-activities"
    )

def monitoring_footprint_output(
    product_activity,
    lcia_method,
    company="unknown",
    event_id="unknown",
    scenario_df=None,
    scenario_col=None,
    amount=1.0,
):

    if scenario_df is not None:
        return _monitoring_footprint_output_with_scenario(
            product_activity=product_activity,
            lcia_method=lcia_method,
            scenario_df=scenario_df,
            scenario_col=scenario_col,
            amount=amount,
            company=company,
            event_id=event_id,
        )

    # --- 1. Total impact ---
    lca = product_activity.lca(lcia_method)

    # --- 2. Auto-find machining activity ---
    machining_activity = get_machining_activity(product_activity)

    # --- 3. Contribution analysis ---
    ca_df = bwa.utils.recursive_calculation_to_object(
        machining_activity,
        lcia_method=lcia_method,
        max_level=1,
        cutoff=0,
        as_dataframe=True,
    )

    operations = [
        {
            "operation": row["name"],
            "score": round(row["score"], 6),
        }
        for _, row in ca_df[ca_df["parent"] == "root"].iterrows()
    ]

    report = {
        "product": product_activity["name"],
        "total_climate_impact_kg_co2eq": round(lca.score, 4),
        "machining_contributions": operations,
    }

    # --- 4. Export to JSON file ---
    filename = f"monitoring_{company}_{event_id}_{date.today().isoformat()}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Exported to {filename}")

    return report

def get_transport_activity(total_activity):
    """Find the A2 transport activity by searching direct exchanges,
    then one level deeper, matching on 'a2:' substring."""

    # First, search direct exchanges
    for exchange in total_activity.exchanges():
        linked = exchange.input
        if "a2:" in linked["name"].lower():
            return linked

    # If not found, search one level deeper through sub-activities
    for exchange in total_activity.exchanges():
        linked = exchange.input
        try:
            for sub_exchange in linked.exchanges():
                sub_linked = sub_exchange.input
                if "a2:" in sub_linked["name"].lower():
                    return sub_linked
        except Exception:
            continue

    raise ValueError(
        f"No A2 transport activity found in exchanges of '{total_activity['name']}' "
        f"or its direct sub-activities"
    )


def get_materials_activity(total_activity):
    """Find the A1 material input activity by searching direct exchanges,
    then one level deeper, matching on 'a1:' substring."""

    # First, search direct exchanges
    for exchange in total_activity.exchanges():
        linked = exchange.input
        if "a1:" in linked["name"].lower():
            return linked

    # If not found, search one level deeper through sub-activities
    for exchange in total_activity.exchanges():
        linked = exchange.input
        try:
            for sub_exchange in linked.exchanges():
                sub_linked = sub_exchange.input
                if "a1:" in sub_linked["name"].lower():
                    return sub_linked
        except Exception:
            continue

    raise ValueError(
        f"No A1 material input activity found in exchanges of '{total_activity['name']}' "
        f"or its direct sub-activities"
    )


def lcia_score_for_named_input(
    parent_activity,
    name_fragment,
    method,
    scenario_df=None,
    scenario_col=None,
    amount=1.0,
):
    """Score direct inputs whose activity names contain ``name_fragment``."""
    matches = [
        exchange
        for exchange in parent_activity.technosphere()
        if name_fragment.lower() in exchange.input.get("name", "").lower()
    ]
    if not matches:
        raise ValueError(
            f"No input containing '{name_fragment}' found in "
            f"{parent_activity.get('name')}"
        )

    total_score = 0.0
    for exchange in matches:
        input_activity = exchange.input
        input_amount = float(exchange["amount"]) * amount

        if scenario_df is None:
            lca = input_activity.lca(method)
            lca.redo_lcia({input_activity.id: input_amount})
            total_score += float(lca.score)
        else:
            from reed.swapping_data import lcia_for_activity_with_scenario

            score, _ = lcia_for_activity_with_scenario(
                activity=input_activity,
                method=method,
                scenario_df=scenario_df,
                scenario_col=scenario_col,
                amount=input_amount,
            )
            total_score += float(score)

    return total_score


def monitoring_dpp_output(
    product_activity,
    lcia_method,
    company="unknown",
    event_id="unknown",
    scenario_df=None,
    scenario_col=None,
    amount=1.0,
):
    """Calculate and export the finished monitoring DPP result."""
    phase_scores = {
        phase: lcia_score_for_named_input(
            parent_activity=product_activity,
            name_fragment=phase,
            method=lcia_method,
            scenario_df=scenario_df,
            scenario_col=scenario_col,
            amount=amount,
        )
        for phase in ("A1", "A2", "A3")
    }
    report = make_dpp_output(
        company=company,
        event_id=event_id,
        product=product_activity["name"],
        country=product_activity.get("location"),
        publication_date=date.today(),
        score_a1=phase_scores["A1"],
        score_a2=phase_scores["A2"],
        score_a3=phase_scores["A3"],
    )

    filename = f"DPP_{company}_{event_id}_{date.today().isoformat()}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Exported to {filename}")

    return report


def simulation_footprint_output(
    product_activity,
    lcia_method,
    company="unknown",
    event_id="unknown",
    scenario_df=None,
    scenario_col=None,
    amount=1.0,
):

    if scenario_df is not None:
        return _simulation_footprint_output_with_scenario(
            product_activity=product_activity,
            lcia_method=lcia_method,
            scenario_df=scenario_df,
            scenario_col=scenario_col,
            amount=amount,
            company=company,
            event_id=event_id,
        )

    # --- 1. Total impact --- capture score immediately before any redo_lcia
    lca = product_activity.lca(lcia_method)
    total_impact = round(lca.score, 4)  # <-- capture here, not later

    # --- 2. A3: Machining — operation-level breakdown ---
    machining_activity = get_machining_activity(product_activity)

    machining_ca_df = bwa.utils.recursive_calculation_to_object(
        machining_activity,
        lcia_method=lcia_method,
        max_level=1,
        cutoff=0,
        as_dataframe=True,
    )

    machining_operations = [
        {
            "operation": row["name"],
            "score": round(row["score"], 6),
        }
        for _, row in machining_ca_df[machining_ca_df["parent"] == "root"].iterrows()
    ]

    # --- 3. A2: Transport — total impact only ---
    transport_activity = get_transport_activity(product_activity)
    lca.redo_lcia({transport_activity.id: 1})
    transport_impact = round(lca.score, 4)

    # --- 4. A1: Raw materials — total impact only ---
    materials_activity = get_materials_activity(product_activity)
    lca.redo_lcia({materials_activity.id: 1})
    materials_impact = round(lca.score, 4)

    # --- 5. Assemble report ---
    report = {
        "product": product_activity["name"],
        "total_climate_impact_kg_co2eq": total_impact,  # <-- uses captured value
        "a1_raw_materials": {
            "total_kg_co2eq": materials_impact,
        },
        "a2_transport": {
            "total_kg_co2eq": transport_impact,
        },
        "a3_machining": {
            "total_kg_co2eq": round(
                sum(op["score"] for op in machining_operations), 4
            ),
            "operations": machining_operations,
        },
    }

    # --- 6. Export to JSON ---
    filename = f"simulation_{company}_{event_id}_{date.today().isoformat()}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Exported to {filename}")

    return report


def _simulation_footprint_output_with_scenario(
    product_activity,
    lcia_method,
    scenario_df,
    scenario_col,
    amount,
    company,
    event_id,
):
    """Create the simulation report using scenario technosphere values."""
    from reed.swapping_data import lcia_for_activity_with_scenario

    total_impact, lca = lcia_for_activity_with_scenario(
        activity=product_activity,
        method=lcia_method,
        scenario_df=scenario_df,
        scenario_col=scenario_col,
        amount=amount,
    )

    materials_impact = _scenario_score(lca, get_materials_activity(product_activity))
    transport_impact = _scenario_score(lca, get_transport_activity(product_activity))
    machining_operations = _scenario_machining_operations(product_activity, lca)

    report = {
        "product": product_activity["name"],
        "total_climate_impact_kg_co2eq": round(float(total_impact), 4),
        "a1_raw_materials": {
            "total_kg_co2eq": round(materials_impact, 4),
        },
        "a2_transport": {
            "total_kg_co2eq": round(transport_impact, 4),
        },
        "a3_machining": {
            "total_kg_co2eq": round(
                sum(operation["score"] for operation in machining_operations), 4
            ),
            "operations": machining_operations,
        },
    }

    filename = f"simulation_{company}_{event_id}_{date.today().isoformat()}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Exported to {filename}")

    return report


def _monitoring_footprint_output_with_scenario(
    product_activity,
    lcia_method,
    scenario_df,
    scenario_col,
    amount,
    company,
    event_id,
):
    """Create the unfinished monitoring report from scenario matrix values."""
    from reed.swapping_data import lcia_for_activity_with_scenario

    total_impact, lca = lcia_for_activity_with_scenario(
        activity=product_activity,
        method=lcia_method,
        scenario_df=scenario_df,
        scenario_col=scenario_col,
        amount=amount,
    )
    operations = _scenario_machining_operations(product_activity, lca)

    report = {
        "product": product_activity["name"],
        "total_climate_impact_kg_co2eq": round(float(total_impact), 4),
        "machining_contributions": operations,
    }

    filename = f"monitoring_{company}_{event_id}_{date.today().isoformat()}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Exported to {filename}")

    return report


def _scenario_score(lca, activity, amount=1.0):
    lca.lci(demand={activity.id: float(amount)})
    lca.lcia()
    return float(lca.score)


def _scenario_machining_operations(product_activity, lca):
    machining_activity = get_machining_activity(product_activity)
    operations = []

    for exchange in machining_activity.technosphere():
        matrix_amount = float(
            lca.technosphere_matrix[
                lca.dicts.product[exchange.input.id],
                lca.dicts.activity[machining_activity.id],
            ]
        )
        if exchange.get("type") in ("technosphere", "generic technosphere"):
            matrix_amount *= -1

        operations.append(
            {
                "operation": exchange.input.get("name", ""),
                "score": round(
                    _scenario_score(lca, exchange.input, matrix_amount), 6
                ),
            }
        )

    return operations
