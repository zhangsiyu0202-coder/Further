# Advanced Analytical Methodologies

To elevate the analysis from simple observation to rigorous scientific inquiry, apply these methodologies where data permits.

## 1. Statistical Rigor & Hypothesis Testing
When comparing groups (e.g., Control vs. Experiment, or different agent types), visual difference is not enough.
- **Action**: Use `scipy.stats` to perform hypothesis testing.
  - For continuous variables (normal dist): **T-test** or **ANOVA**.
  - For non-normal/ordinal data: **Mann-Whitney U** or **Kruskal-Wallis**.
  - For categorical data: **Chi-Square** test.
  - For regression/correlation: **OLS Regression** via `statsmodels.api` or `scipy.stats.linregress`.
- **Reporting**: MUST report **p-values** and **effect sizes** (e.g., Cohen's d) in the text. State significance explicitly (e.g., "p < 0.05 indicates a significant difference").

## 2. Social Network Analysis (SNA)
If `agent_dialog` or interaction logs are available, treat the society as a graph.
- **Construction**: Build a graph `G` where nodes are agents and edges represent interactions (messages, trades, etc.).
- **Metrics to Calculate**:
  - **Degree Centrality**: Who are the influencers?
  - **Clustering Coefficient**: Are echo chambers forming?
  - **Path Length**: How fast can information spread?
  - **Community Detection**: Use Louvain or Leiden algorithms to find subgroups.
- **Visualization**: Plot the network using `networkx` with `matplotlib`, coloring nodes by agent state/opinion.

## 3. Temporal Dynamics & Convergence
Simulation is a process, not just a final state. Analyze the *trajectory*.
- **Convergence Check**: specific metrics (e.g., avg opinion) stabilize over `step`? Calculate the standard deviation of the last N steps to confirm stability.
- **Phase Transitions**: Look for sudden spikes or drops (tipping points) in time-series data using `np.gradient`.
- **Visualization**: Line charts with error bands (confidence intervals) over time.

## 4. Inequality & Distribution Analysis
Averages hide inequality.
- **Metrics**:
  - **Gini Coefficient**: For wealth or resource distribution.
  - **Entropy / Herfindahl Index**: For diversity of opinions or topics.
  - **Polarization Index**: For opinion dynamics (are agents clustering at extremes?).
- **Visualization**: Lorenz Curve, KDE plots (distributions), or Box-plots to show variance.

## 5. Text & Sentiment Mining (NLP)
If specific `agent_dialog` content is relevant:
- **Topic Modeling**: Use simple TF-IDF or keyword extraction to summarize what agents are talking about.
- **Sentiment Trajectory**: Track how the average sentiment (positive/negative) changes over time.
- **Correlation**: Does sentiment correlate with decision outcomes?

## 6. Synthesis & Comparative Analysis (Cross-Experiment)
When synthesizing results across multiple experiments (e.g., varying a parameter):
- **Parameter Sensitivity**: Plot outcome metrics vs. parameter values. Is the relationship linear, exponential, or U-shaped?
- **Robustness Check**: Do findings hold across different seeds or slight variations?
- **Meta-Analysis**: If multiple runs exist, aggregate their effect sizes.

## 7. Causal Inference (Bonus)
If observing a strong correlation (e.g., "more friends -> higher wealth"), attempt to check causality if the experiment design (Intervention) allows it. Compare the "Intervention" group against "Control" specifically on the perturbed variable.
