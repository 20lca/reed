import pandas as pd
import bw2analyzer as bwa


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

