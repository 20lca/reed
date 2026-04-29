#Script with functions for inserting sensordata into the reed database

import pandas as pd
from collections import defaultdict
import bw2data as bd
import bw2calc as bc
import numpy as np
import bw_processing as bwp

def find_activities_by_name(db, needle: str, exact=False):
    needle = str(needle)
    if exact:
        return [act for act in db if act.get("name") == needle]
    else:
        n = needle.lower()
        return [act for act in db if n in act.get("name", "").lower()]
    
def electricity_input_amount(activity, electricity_act):
    """Amount of electricity input per 1 unit output of activity. 0 if missing."""
    for exc in activity.technosphere():
        if exc.input.id == electricity_act.id:
            return float(exc["amount"])
    return 0.0

def get_product_id_for_activity(activity):
    """
    Returns a product-row identifier for scenario tables.
    For normal activities: rp_exchange().output.id
    For IO table activities: fall back to activity.id
    """
    try:
        return activity.rp_exchange().output.id
    except ValueError:
        # IO Table activities don't have rp_exchange
        return activity.id

def build_scenarios_from_power_active(tool_energy_by_company_and_event, found, electricity_act):
    
    df_reset = tool_energy_by_company_and_event.reset_index()

    # get company + event_id (only one exists)
    company = df_reset["company"].iloc[0]
    event_id = df_reset["event_id"].iloc[0]
    scenario_name = f"{company}_{event_id}"

    pa_by_tool = df_reset.set_index("reed tool")["Power_Active"]

    electricity_product_id = get_product_id_for_activity(electricity_act)

    rows = []
    original_vals = []
    swapped_vals = []

    for tool, matches in found.items():
        hour_matches = [a for a in matches if a.get("unit") == "hour"]
        if not hour_matches:
            continue

        act = hour_matches[0]

        if tool not in pa_by_tool.index:
            continue

        orig = electricity_input_amount(act, electricity_act)
        swap = float(pa_by_tool.loc[tool])* 3.6e-6 #kWh --> TJ

        rows.append((electricity_product_id, act.id))
        original_vals.append(orig)
        swapped_vals.append(swap)

    scenarios = pd.DataFrame(
        {"original": original_vals, scenario_name: swapped_vals},
        index=pd.MultiIndex.from_tuples(rows, names=["product", "activity"])
    )

    return scenarios

def build_input_to_consumers_index(db):
    """input_activity_id -> list of (consumer_activity, exchange) where input is used."""
    idx = defaultdict(list)
    for consumer in db:
        for exc in consumer.technosphere():
            idx[exc.input.id].append((consumer, exc))
    return idx

def build_consumer_input_scenarios_from_hours(
    tool_energy_by_company_and_event,
    found,
    reed,
):
    """
    Builds a scenarios DataFrame that replaces technosphere inputs of the found tool activities
    when they are used as inputs by other activities.

    Rows are (product, activity) = (tool_activity.id, consumer_activity.id)
    'original' is the existing exchange amount.
    scenario column is set to df 'hours' for that tool.
    """
    df_reset = tool_energy_by_company_and_event.reset_index()

    # single company/event
    company = df_reset["company"].iloc[0]
    event_id = df_reset["event_id"].iloc[0]
    scenario_name = f"{company}_{event_id}"

    # tool -> hours (from df)
    hours_by_tool = df_reset.set_index("reed tool")["hours"]

    # reverse index: who uses whom
    input_to_consumers = build_input_to_consumers_index(reed)

    rows = []
    original_vals = []
    swapped_vals = []

    for tool, matches in found.items():
        if tool not in hours_by_tool.index:
            continue
        new_hours = float(hours_by_tool.loc[tool])

        # pick hour-version(s) of the tool activity
        tool_acts = [a for a in matches if a.get("unit") == "hour"]
        if not tool_acts:
            continue

        for tool_act in tool_acts:
            consumers = input_to_consumers.get(tool_act.id, [])
            if not consumers:
                continue

            for consumer, exc in consumers:
                if company.lower() not in consumer.get("name", "").lower():
                    continue

                if exc.get("unit") != "hour":
                    continue

                orig = float(exc["amount"])

                rows.append((tool_act.id, consumer.id))
                original_vals.append(orig)
                swapped_vals.append(new_hours)

    scenarios = pd.DataFrame(
        {"original": original_vals, scenario_name: swapped_vals},
        index=pd.MultiIndex.from_tuples(rows, names=["product", "activity"]),
    )

    return scenarios

def describe_scenarios(scenarios_df):
    rows = []

    for product_id, activity_id in scenarios_df.index:
        product = bd.get_activity(product_id)
        activity = bd.get_activity(activity_id)

        rows.append({
            "product_name": product.get("name"),
            "product_unit": product.get("unit"),

            "activity_name": activity.get("name"),
            "activity_unit": activity.get("unit"),
        })

    readable = pd.DataFrame(rows)

    # append scenario values
    readable = readable.join(scenarios_df.reset_index(drop=True))

    return readable

def lcia_for_activity_with_scenario(
    activity,
    method,
    scenario_df,
    scenario_col=None,
    amount=1.0,
    use_arrays=True,
):
    """
    Run LCIA for `amount` of `activity`, applying technosphere overrides from `scenario_df`.

    Parameters
    ----------
    activity : bw2data Activity
    method : tuple
        LCIA method tuple, e.g. config.lcia_gwp100
    scenario_df : pd.DataFrame
        Index: MultiIndex (product, activity) -> technosphere indices
        Columns: includes scenario values. If scenario_col is None, uses the last column.
    scenario_col : str | None
        Which column in scenario_df to apply (e.g. "VWR_12345"). If None, uses last column.
    amount : float
        Demand amount for the activity.
    use_arrays : bool
        Keep True for performance with bw_processing.

    Returns
    -------
    score : float
    lca : bc.LCA
        The LCA object (so you can do contribution analysis afterwards if you want).
    """
    # pick scenario column
    if scenario_col is None:
        # assume columns are like ["original", "<scenario_name>"] or multiple scenarios
        scenario_col = [c for c in scenario_df.columns if c != "original"][-1]

    # Build datapackage with the scenario column only
    dp = bwp.create_datapackage(sequential=True)

    indices = scenario_df.index.values.astype(bwp.INDICES_DTYPE)
    values = scenario_df[[scenario_col]].values  # shape (n, 1) for sequential

    dp.add_dynamic_array(
        matrix="technosphere_matrix",
        indices_array=indices,
        interface=values,
        flip_array=np.full(indices.shape[0], True),
    )

    # Prepare FU and base data objects (includes biosphere + characterization etc.)
    fu, data_objs, _ = bd.prepare_lca_inputs({activity: amount}, method=method)

    # Run LCA with scenario datapackage appended
    lca = bc.LCA(demand=fu, method=method, data_objs=data_objs + [dp], use_arrays=use_arrays)
    lca.lci()
    lca.lcia()

    return lca.score, lca

def find_subactivity_by_name_fragment(parent_activity, name_fragment):
    """
    Find technosphere input activities under a parent activity
    where the input activity name contains `name_fragment`.
    """
    name_fragment = name_fragment.lower()

    matches = []

    for exc in parent_activity.technosphere():
        input_act = exc.input

        if name_fragment in input_act.get("name", "").lower():
            matches.append(input_act)

    return matches

def build_consumer_input_scenarios_from_hours_for_activity(
    tool_energy_by_company_and_event,
    found,
    consumer_activity,
):
    """
    Builds a scenario DataFrame that replaces tool-hour inputs inside one specific
    consumer activity, e.g. the A3 activity used by KOMATSU total.

    Rows are:
        (product, activity) = (tool_activity.id, consumer_activity.id)

    This means:
        replace the amount of tool_activity consumed by consumer_activity.
    """

    df_reset = tool_energy_by_company_and_event.reset_index()

    company = df_reset["company"].iloc[0]
    event_id = df_reset["event_id"].iloc[0]
    scenario_name = f"{company}_{event_id}"

    hours_by_tool = df_reset.set_index("reed tool")["hours"]

    rows = []
    original_vals = []
    swapped_vals = []

    for tool, matches in found.items():
        if tool not in hours_by_tool.index:
            continue

        new_hours = float(hours_by_tool.loc[tool])

        tool_acts = [a for a in matches if a.get("unit") == "hour"]

        for tool_act in tool_acts:
            for exc in consumer_activity.technosphere():
                if exc.input.id != tool_act.id:
                    continue

                orig = float(exc["amount"])

                rows.append((tool_act.id, consumer_activity.id))
                original_vals.append(orig)
                swapped_vals.append(new_hours)

    scenarios = pd.DataFrame(
        {"original": original_vals, scenario_name: swapped_vals},
        index=pd.MultiIndex.from_tuples(rows, names=["product", "activity"]),
    )

    return scenarios