# Visualization Reliability Rules

- Before proposing charts, check table row counts from provided schema.
- If target tables are empty, do not propose hypothesis charts that require them.
- In empty-data cases, propose a diagnostic chart first:
  - table row count bar chart, or
  - missingness/availability diagnostic figure.
- For each planned chart, provide a concrete `tool_description` that can be executed directly.
- If previous attempt failed, revise plan based on retry feedback and keep at least one deliverable chart.

# Performance & Memory Safety

- If a table has **> 50,000 rows**, strictly use **sampling** (`df.sample(n=10000)`) for complex visualizations (e.g., scatter plots, pair plots, swarm plots) to prevent memory crashes.
- For statistical aggregation (mean, sum, count), use the full dataset (`df`) or SQL queries.
- Do not attempt to render interactive HTML plots for datasets > 5,000 points; use static images (`plt.savefig`) instead.
