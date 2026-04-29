def lca_score(process_dict, method):
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

def plot_contribution(df,
                      title='Contribution Analysis',
                      xlabel='CO2 eq. emissions (kg)',
                      drop_parent=True):
    df_plot = df.copy()

    # Drop the parent (the demand itself)
    if drop_parent:
        # Heuristic: parent is usually the one with maximum score
        parent_score = df_plot['score'].max()
        df_plot = df_plot[df_plot['score'] < parent_score]

    # Sort descending by contribution
    df_plot = df_plot.sort_values(by='score', ascending=False)

    f, ax = plt.subplots(figsize=(5, 2))
    sns.barplot(y='name', x='score', data=df_plot, ax=ax)

    ax.set(
        title=title,
        xlabel=xlabel,
        ylabel=''
    )
    plt.tight_layout()
    plt.show()