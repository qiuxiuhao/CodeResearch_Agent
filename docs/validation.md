# Validation

## Full Validation

```bash
bash scripts/validate.sh
```

The script runs:

1. Backend pytest.
2. Frontend dependency install.
3. Frontend tests.
4. Frontend production build.

## Manual Commands

Backend:

```bash
conda run -n code-research-agent pytest -q
```

Frontend:

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

## Startup Check

```bash
bash scripts/dev.sh
```

Then open:

```text
http://127.0.0.1:5173
```

Backend health:

```text
http://127.0.0.1:8000/health
```

## Demo Check

- Create a task with `examples/small_pytorch_project.zip`.
- Confirm overview, files, functions, current-task library notes, global function library, models, diagrams, and report pages load.
- Toggle beginner mode and open a library function explanation modal.

## Cleanup Before Commit

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -type f -delete
rm -rf .pytest_cache code_research_agent.egg-info
rm -rf frontend/node_modules frontend/dist frontend/.vite frontend/*.tsbuildinfo
rm -rf data/*.sqlite3 data/*.sqlite3-*
rm -rf outputs/task_*
```
