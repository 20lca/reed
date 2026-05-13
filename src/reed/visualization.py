
import seaborn as sns
import matplotlib.pyplot as plt

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