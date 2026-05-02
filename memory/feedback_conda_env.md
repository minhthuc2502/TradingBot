---
name: Use thuc-dev conda environment
description: Always use the thuc-dev conda environment when running Python/pip commands in TradingBot project
type: feedback
---

Always activate and use the `thuc-dev` conda environment for all Python, pip, and pytest commands in this project.

**Why:** User specified this as the project's active environment.

**How to apply:** Prefix all Python/pip/pytest commands with `conda run -n thuc-dev` or activate with `conda activate thuc-dev &&` before running commands. Example: `conda run -n thuc-dev pip install ...` or `conda run -n thuc-dev python -m pytest ...`
