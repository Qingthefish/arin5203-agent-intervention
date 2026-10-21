# Contributing

Agent Memory Crash Test is an early research toolkit. Small, reviewable changes
that improve reproducibility, contract authoring, framework adapters, or
failure reporting are welcome.

## Development setup

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 scripts/index_experiment_artifacts.py --check
```

The deterministic crash-test path must remain usable without an API key or
model download. Model-backed experiment runners are plan-only unless both
explicit execution flags are supplied.

## Pull requests

- Explain the user-visible failure mode or interface change.
- Add or update deterministic tests.
- Do not rewrite immutable experiment artifacts.
- Keep gold decisions and private oracle facts out of model-visible inputs.
- Preserve matched siblings in the same split.
- Do not add company data, credentials, or unverifiable production claims.

By contributing, you agree that your contribution is licensed under the MIT
License that covers this repository.
