# Core test evidence

Date: 2026-10-30. Scope: pure Python preflight rules and immutable snapshot/report contracts.

1. Wrote `tests/test_core.py` before `framewright/core.py` existed. Ran `uv run --python 3.11 --no-project python -m unittest discover -s tests -p test_core.py -v`; exit 1 with `ModuleNotFoundError: No module named 'framewright.core'`.
2. Added texture-policy tests after the user clarified that Sundown is an integration destination and AAA/8K targets must remain flexible.
3. Implemented the core. The same test command passed all 45 tests in 0.003 seconds on Python 3.11.
4. Ran Ruff import checks and formatting for both owned Python files, then repeated the 45 tests successfully.

Coverage includes clean assets, structural errors, intentional open geometry, budget boundaries, immutable inputs, rig target lookup and weight checks, animation ranges, lighting presence, deterministic JSON reports, configurable texture targets and invalid texture dimensions/policy values. All six profiles are provisional starting policies, with `cinematic_8k` explicitly configurable.

Limits: the core uses captured facts; it does not judge silhouette, anatomy, motion, deformation, rendered lighting, texture detail, or engine performance. World/light presence is only a presence check. A texture below the chosen resolution target receives advice, never a claim that larger images improve quality. `passed` means no structural ERROR findings.
