## 2026-04-07 - Replace pd.DataFrame.iterrows() with to_dict("records")
**Learning:** Pandas `iterrows()` is incredibly slow because it wraps every row in a Series object on each iteration. In environments where thousands of rows need processing (like the alpha loop), this creates significant overhead. `itertuples()` is much faster but returns namedtuples which require `row.column` or `getattr()` access, causing refactoring overhead. `to_dict("records")` provides a great middle-ground: it's roughly 10x-20x faster than `iterrows()` and outputs native Python dictionaries, meaning existing `row["column"]` or `row.get("column")` access works flawlessly without major refactoring.
**Action:** When iterating over pandas DataFrames in scoring or alpha loops, always use `to_dict("records")` instead of `iterrows()` if column data is accessed dynamically or extensively, or use `itertuples()` if dot access is acceptable. Never use `iterrows()`.
<<<<<< perf/optimize-strategies-iterrows-10941796727025481878

## $(date +%Y-%m-%d) - Optimization: Replace Pandas iterrows() with to_dict('records')
**Learning:** `pd.DataFrame.iterrows()` is very inefficient for simple row iteration because it wraps every row in a `pd.Series` object. Using `to_dict('records')` converts the dataframe to a list of dictionaries, offering a massive performance boost (often 3-10x faster) while maintaining intuitive key-based access syntax.
**Action:** Always prefer `to_dict('records')` or `itertuples()` over `iterrows()` when iterating through Pandas DataFrames, and update function parameter type hints (e.g., to `Mapping[str, Any]`) to support dictionary inputs instead of enforcing `pd.Series`.
=======
<<<<<< optimize-strategies-iter-16849240214755962494
## 2024-03-08 - Optimize iterrows using to_dict('records')
**Learning:** `iterrows()` is extremely slow for large Pandas DataFrames. Replacing it with `to_dict('records')` allows fast native dictionary operations that are ~6x faster in this codebase for 10k rows.
**Action:** When iterating over DataFrames, favor `to_dict('records')` or `itertuples()` instead of `iterrows()` for a free performance boost.
=======

## 2024-03-24 - Mocking correlations for portfolio limits testing
**Learning:** Testing portfolio correlation scaling in `portfolio/risk_manager.py` can be simplified by either instantiating stub signals with specific `market_id` and `strategy` combinations to trigger the structural fallback, or by directly mocking `_empirical_correlation` to return a controlled correlation matrix.
**Action:** When testing portfolio risk adjustments, prefer mocking the underlying risk metrics (like the empirical correlation matrix) directly rather than trying to construct intricate historical data scenarios that satisfy deep internal data fetching logic.
>>>>>> main
>>>>>> main
