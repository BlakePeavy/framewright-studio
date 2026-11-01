# Protocol TDD evidence

2026-10-30: wrote `tests/test_api.py` before `framewright/api.py`. Ran
`uv run --python 3.11 python -m unittest discover -s tests -p test_api.py -v`.
Observed expected RED: `ModuleNotFoundError: No module named 'framewright.api'`.

Cases cover capabilities without Blender, inspection, configurable profile validation,
preview defaults, explicit derivative edits, malformed/unrecognized input rejected before
adapter access, failure responses, and request immutability. Final green run is recorded
in `docs/verification.md` with the integrated checks.

The batch job boundary also started RED: six file-boundary tests reported
`ModuleNotFoundError: No module named 'scripts.blender_job'` before the runner existed.
After implementation all six passed. Independent review then identified a report
creation race after saving. Four regression tests were added; three failed before
the correction. After reserving reports before dispatch and disclosing partial save
outcomes, all ten job tests passed. The source file and existing outputs remain protected.

End-to-end reopening then exposed an empty `.blend1` backup of the reserved destination.
A real-Blender regression and a unit test failed before the fix. The batch save now
temporarily disables versioned backups only for that save and restores the process
setting afterward. No live preferences are saved. Both regressions pass in final verification.
