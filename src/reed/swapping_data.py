#Script with functions for inserting sensordata into the reed database

import pandas as pd
from collections import defaultdict
import bw2data as bd

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

def build_scenarios_from_power_active(tool_energy_by_company_and_event, found, electricity_act):
    
    df_reset = tool_energy_by_company_and_event.reset_index()

    # get company + event_id (only one exists)
    company = df_reset["company"].iloc[0]
    event_id = df_reset["event_id"].iloc[0]
    scenario_name = f"{company}_{event_id}"

    pa_by_tool = df_reset.set_index("reed tool")["Power_Active"]

    rows = []
    original_vals = []
    swapped_vals = []

    for tool, matches in found.items():
        # kun hour-aktiviteter
        hour_matches = [a for a in matches if a.get("unit") == "hour"]
        if not hour_matches:
            continue

        act = hour_matches[0]
        orig = electricity_input_amount(act, electricity_act)
        swap = float(pa_by_tool.loc[tool])* 3.6e-6 #kWh --> TJ

        rows.append((electricity_act.id, act.id))
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
            
            if company.lower() not in consumer.get("name", "").lower():
                continue

            for consumer, exc in consumers:
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
            "product_ref": product.get("reference product"),
            "product_unit": product.get("unit"),
            "product_location": product.get("location"),

            "activity_name": activity.get("name"),
            "activity_ref": activity.get("reference product"),
            "activity_unit": activity.get("unit"),
            "activity_location": activity.get("location"),
        })

    readable = pd.DataFrame(rows)

    # append scenario values
    readable = readable.join(scenarios_df.reset_index(drop=True))

    return readable