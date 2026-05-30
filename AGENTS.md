## Repository guardrails

- This is a research-only repository. Do not add broker credentials, order placement, or live allocation logic here.
- Keep checks small and bounded. Prefer targeted tests over full-suite or data-heavy jobs.
- Do not commit raw licensed market data. Use small synthetic examples or point-in-time derived artifacts.
- Heavy data collection or backtests should run through GitHub Actions or `slowrun bash -lc "..."` from the parent VPS.

