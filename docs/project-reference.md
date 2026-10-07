## Repository guardrails

- This is a research-only repository. Do not add broker credentials, order placement, or live allocation logic here.
- Keep checks small and bounded. Prefer targeted tests over full-suite or data-heavy jobs.
- Do not commit raw licensed market data. Use small synthetic examples or point-in-time derived artifacts.
- For an explicitly authorized heavy collection or backtest, use the approved GitHub Actions job or the parent VPS `slowrun` environment. Reading this file or making a local code change does not authorize remote dispatch or data acquisition.

