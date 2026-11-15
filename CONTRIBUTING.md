# Contributing to RouteLake

Thanks for considering a contribution. RouteLake is an engineering prototype; contributions should preserve deterministic behavior and clearly label assumptions.

## Before opening a PR
- Open an issue for substantial changes and describe the problem and proposed behavior.
- Keep changes focused; avoid introducing third-party dependencies without discussion.
- Add or update tests for behavior changes, including edge cases and failure paths.
- Update relevant docs and examples. Never present illustrative cost assumptions as measured savings.

## Local checks
```bash
python -m compileall -q routelake tests
python -W error -m unittest discover -s tests -v
python -m routelake demo
```

## Pull requests
Explain the motivation, design, compatibility impact, tests run, and documentation changes. Include sample output when changing CLI behavior. Do not include credentials, customer data or proprietary billing exports.
