import bw2data as bd
import bw2io as bi
import bw2calc as bc
import numpy as np
import bw_processing as bwp


def setup_project():

    bd.projects.set_current('reed')

    # add an example database
    if 'Mobility example' not in bd.databases:
        bi.add_example_database()

def run_simple_calc(act_names=['Driving an combustion car'],
                    amounts=[1]):
    """_summary_

    Returns:
        _type_: lca score
    """

    bd.projects.set_current('reed')
    lcia_method = ('IPCC', 'simple')
    mobility_example_db = bd.Database('Mobility example')

    functional_unit = {mobility_example_db.get(name=name):amount for name,amount
                       in zip(act_names,amounts)}

    lca = bc.LCA(demand=functional_unit,method=lcia_method)
    lca.lci()
    lca.lcia()
    print(lca.score)
    return lca.score

def run_advanced_calc():

    pass


if __name__ == "__main__":
    
    setup_project()
    run_simple_calc()

