import pandas as pd
import bw2analyzer as bwa
from datetime import date
import json

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

def monitoring_footprint_output(product_activity, lcia_method, company="unknown", event_id="unknown"):

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
            "amount": round(row["amount"], 6),
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