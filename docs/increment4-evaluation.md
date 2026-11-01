# Technical evaluation corpus and candidate ranking

Implemented the offline FW-062 evaluation/ranking increment on 2026-10-30. It compares
explicit supplied plans against measured structural outcomes and source fingerprints.
It does not select an artistic winner, call a cloud model, execute supplied code or
invent provider charges. Artist approval remains `not_evaluated`.

## Corpus

`benchmarks/evaluation-corpus.json` is a strict schema `1.0` corpus with eight synthetic
snapshot cases: healthy prop, collapsed faces, unweighted skin, invalid FPS, missing
review lighting, low source texture resolution, intentional open surface and loose
vertices. It records exact expected diagnostic rule sets, error counts and structural
pass flags. Deliberately broken cases pass the *evaluation* only when the actual
validator detects their expected defects; their asset reports remain failing where
appropriate. Warning-only open boundaries are not relabeled as broken geometry.

`evaluate_snapshot_corpus(path, expected_sha256=None)` checks a bounded 1 MiB file,
unique JSON keys, schema, typed snapshots and expected values. It runs the actual
`scene.validate` API through workflows with equality gates. Fresh workflow IDs prevent
an earlier replay-cache result from skipping measurement. Before/after hashes cover
the frozen source snapshots. No Blender or asset files are needed for this pure corpus.

The checked-in corpus SHA256 is
`91f1b16b98a7b1727e5cd529a40adb91438e5b0ed00c46435516473fc4ee7627`.
A local run recorded eight expected outcomes with unchanged source hashes in
`artifacts/evaluation-corpus-report.json`. This is a structural regression corpus,
not an artist-reviewed representative production benchmark.

`benchmarks/evaluation-repair-plans.json` is a separate schema `1.0` replay file. It
contains explicit loose-vertex plan/apply and inspection-only workflows for the owned
`EvaluationSource` fixture. The Blender acceptance script measures their real geometry
and diagnostics; no successful response flags are substituted for diagnostic results.

## Evaluation and ranking API

`evaluate(provider, cases, runner, source_probe=None, ...)` retains the existing
success/regression/latency report and adds:

- `plan_valid`, `executed` and nullable `source_preserved` per case.
- Optional exact `expected_rule_ids` and `require_preservation` expectations.
- Trusted before/after lowercase SHA256 probes, including when a runner raises.
- A stop on detected source change or unavailable post-execution preservation evidence.
  Later cases are explicitly recorded as unexecuted, preventing evaluation of contaminated inputs.

The probe is trusted host code and must cover the source data the caller intends to
protect. A hash of limited fields only establishes preservation of those fields.
Absent evidence remains unknown. Invalid probe evidence prevents execution; a required
preservation check cannot pass without a successful comparison. Baseline
`mesh.remove_loose_vertices` uses the same explicit mutation authorization as newer
commands; inspection/capability commands remain usable without it.

`rank_candidates(candidates, cases, runner, ...)` accepts 1–20 named provider instances
and evaluates them against the same explicit cases, optionally using a baseline report.
The ordering is lexicographic:

1. Valid plans.
2. Verified preservation, then unknown preservation, then measured source damage.
3. Fewer regressions, including removed baseline cases.
4. More successful technical cases.
5. Lower measured mean elapsed time.
6. Lower explicitly reported comparable cost, then a stable candidate-ID tie break.

Optional `reported_costs` maps candidate IDs to
`{"amount": number, "currency": "USD", "evidence": "accounting source"}` or `null`.
Amounts must be finite and nonnegative; evidence is required. Different currencies
are rejected rather than converted implicitly. Missing cost remains `null`, never
zero. Cost only resolves a technical/latency tie and cannot outrank preservation.
These values are caller-reported accounting evidence, not independently verified bills.

A candidate is technically `eligible` only if all plans validate, source preservation
is verified, every case succeeds and no baseline regression/removal occurred. This
is not visual acceptance or permission to publish. Ranking does not automatically
apply a winner. Explicitly authorized mutating evaluation can create derivatives in
the caller's isolated scene; their lifecycle belongs to that caller. Source damage
halts subsequent candidates, lists them in `skipped_candidates` and marks the evaluation
incomplete. No rollback or source repair is silently attempted.

## TDD and observed results

- Initial additions produced one failing baseline-command guard and twelve missing-feature
  errors across the new tests. Implemented the guard, probes, ranking and corpus runner.
- The first corpus execution exposed tuple values reaching strict canonical JSON; source
  hashing now explicitly normalizes snapshot tuples into JSON arrays.
- A typed-corpus regression reproduced negative-count acceptance; count validation now rejects it.
- A source-damage regression showed later cases/candidates still ran on changed inputs;
  the evaluator now stops and reports unexecuted work.
- **28 provider/evaluation Python tests pass**, including malformed/hash/schema inputs,
  real diagnostic-rule mismatches, source damage, baseline removals, comparable/unknown
  costs, latency precedence and explicit mutation authorization.
- **3 real Blender 5.2.1 LTS tests pass**. Plan/apply repair outranks inspection that leaves
  `LOOSE_VERTICES`; the source retains five vertices and its exact fingerprint while the
  hidden derivative has four. Unapproved evaluation creates no derivative. Injected source
  damage disqualifies an otherwise structurally clean result.
- Scoped Ruff lint and formatting pass. Local red/green logs are `artifacts/evaluation-*.log`.

```powershell
uv run python -m unittest discover -s tests -p test_providers.py -v
uv run python -c "from framewright.providers import evaluate_snapshot_corpus; print(evaluate_snapshot_corpus('benchmarks/evaluation-corpus.json'))"
& '<Blender executable>' --background --factory-startup --disable-autoexec --offline-mode --python-exit-code 1 --python scripts/test_evaluation_blender.py
```

Remaining FW-062 acceptance: representative owned production assets, independently
reviewed visual labels, full motion/material/native results, real provider accounting
when providers are adopted, repeated timing distributions and human review of candidate
tradeoffs. The offline implementation does not manufacture those missing observations.
