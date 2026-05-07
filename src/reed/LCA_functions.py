import pandas as pd
import bw2analyzer as bwa


def lca_score(process_dict:dict, method:tuple)->pd.DataFrame:
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

