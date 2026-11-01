"""Provider-neutral plan replay and technical evaluation contracts."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from framewright import providers
from framewright.providers import FileReplayProvider, SuppliedPlanProvider, evaluate
from framewright.workflows import clear_run_cache, run_workflow


def plan(name="eval-run", dry_run=True):
    return {
        "run_id": name,
        "dry_run": dry_run,
        "steps": [
            {"id": "manifest", "command": "asset.manifest_create", "params": {"name": "Fixture"}}
        ],
    }


class ProviderTests(unittest.TestCase):
    def setUp(self):
        clear_run_cache()

    def test_supplied_provider_validates_before_use_and_returns_a_copy(self):
        source = plan()
        provider = SuppliedPlanProvider({"task": source})
        source["steps"].clear()
        first = provider.plan({"id": "task", "context": {}})
        first["steps"].clear()
        self.assertEqual(len(provider.plan({"id": "task"})["steps"]), 1)

    def test_unknown_or_invalid_plans_are_rejected(self):
        invalid = plan()
        invalid["steps"][0]["command"] = "python.exec"
        with self.assertRaises(ValueError):
            SuppliedPlanProvider({"task": invalid})
        with self.assertRaises(ValueError):
            SuppliedPlanProvider({"task": plan()}).plan({"id": "unknown"})

    def test_file_replay_checks_hash_and_keeps_read_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plans.json"
            data = json.dumps({"schema_version": "1.0", "plans": {"task": plan()}}).encode()
            path.write_bytes(data)
            provider = FileReplayProvider(path, expected_sha256=hashlib.sha256(data).hexdigest())
            path.write_text("changed", encoding="utf-8")
            self.assertEqual(provider.plan({"id": "task"})["run_id"], "eval-run")
            with self.assertRaises(ValueError):
                FileReplayProvider(path, expected_sha256=hashlib.sha256(data).hexdigest())

    def test_file_replay_rejects_duplicate_keys_and_future_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plans.json"
            for text in ['{"plans":{},"plans":{}}', '{"schema_version":"2.0","plans":{}}']:
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    FileReplayProvider(path)

    def test_real_pure_workflow_evaluation_has_no_artist_approval(self):
        provider = SuppliedPlanProvider({"task": plan(dry_run=False)})
        result = evaluate(
            provider,
            [
                {
                    "id": "task",
                    "expected_status": "completed",
                    "required_commands": ["asset.manifest_create"],
                }
            ],
            run_workflow,
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["metrics"]["success_rate"], 1.0)
        self.assertEqual(result["artist_approval"], "not_evaluated")

    def test_findings_and_required_rules_affect_technical_success(self):
        provider = SuppliedPlanProvider({"task": plan()})
        result = evaluate(
            provider,
            [
                {
                    "id": "task",
                    "expected_status": "completed",
                    "required_rule_ids": ["BROKEN"],
                    "max_error_findings": 0,
                }
            ],
            lambda _: {
                "status": "completed",
                "findings": [{"rule_id": "BROKEN", "severity": "ERROR"}],
            },
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["cases"][0]["error_findings"], 1)

    def test_baseline_detects_regression_and_improvement_by_case_identity(self):
        provider = SuppliedPlanProvider({"a": plan("a"), "b": plan("b")})
        cases = [
            {"id": "a", "expected_status": "completed"},
            {"id": "b", "expected_status": "completed"},
        ]
        old = evaluate(
            provider, cases, lambda p: {"status": "completed" if p["run_id"] == "a" else "failed"}
        )
        new = evaluate(
            provider,
            cases,
            lambda p: {"status": "failed" if p["run_id"] == "a" else "completed"},
            baseline=old,
        )
        self.assertEqual(new["regressions"], ["a"])
        self.assertEqual(new["improvements"], ["b"])

    def test_mutating_workflow_requires_explicit_evaluation_authorization(self):
        workflow = {
            "run_id": "mutation",
            "dry_run": False,
            "steps": [{"id": "build", "command": "model.build_prop", "params": {}}],
        }
        calls = []
        provider = SuppliedPlanProvider({"task": workflow})
        result = evaluate(
            provider,
            [{"id": "task", "expected_status": "completed"}],
            lambda p: calls.append(p) or {"status": "completed"},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(calls, [])
        result = evaluate(
            provider,
            [{"id": "task", "expected_status": "completed"}],
            lambda p: {"status": "completed"},
            allow_mutation=True,
        )
        self.assertTrue(result["passed"])

    def test_explicit_per_step_preview_does_not_require_mutation_authorization(self):
        workflow = {
            "run_id": "preview",
            "dry_run": False,
            "steps": [{"id": "build", "command": "model.build_prop", "params": {"dry_run": True}}],
        }
        result = evaluate(
            SuppliedPlanProvider({"task": workflow}),
            [{"id": "task", "expected_status": "completed"}],
            lambda p: {"status": "completed"},
        )
        self.assertTrue(result["passed"])

    def test_malformed_status_is_a_validation_error(self):
        with self.assertRaises(ValueError):
            evaluate(
                SuppliedPlanProvider({"task": plan()}),
                [{"id": "task", "expected_status": []}],
                lambda p: {},
            )

    def test_removed_baseline_cases_cannot_silently_pass(self):
        provider = SuppliedPlanProvider({"a": plan("a"), "b": plan("b")})
        baseline = evaluate(
            provider,
            [
                {"id": "a", "expected_status": "validated"},
                {"id": "b", "expected_status": "validated"},
            ],
            run_workflow,
        )
        current = evaluate(
            provider, [{"id": "a", "expected_status": "validated"}], run_workflow, baseline=baseline
        )
        self.assertFalse(current["passed"])
        self.assertEqual(current["removed_cases"], ["b"])

    def test_invalid_corpus_rejects_before_running(self):
        provider = SuppliedPlanProvider({"task": plan()})
        calls = []
        for cases in [
            [],
            [{"id": "task", "expected_status": "completed", "approve_art": True}],
            [{"id": "task", "expected_status": "completed"}] * 2,
        ]:
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                evaluate(provider, cases, lambda p: calls.append(p))
        self.assertEqual(calls, [])

    def test_runner_failure_is_a_recorded_case_failure(self):
        def fail(plan):
            raise RuntimeError("fixture")

        result = evaluate(
            SuppliedPlanProvider({"task": plan()}),
            [{"id": "task", "expected_status": "completed"}],
            fail,
        )
        self.assertFalse(result["cases"][0]["passed"])
        self.assertEqual(result["cases"][0]["error_type"], "RuntimeError")

    def test_case_and_plan_inputs_remain_unchanged(self):
        cases = [{"id": "task", "context": {"note": "Keep"}, "expected_status": "validated"}]
        before = copy.deepcopy(cases)
        evaluate(SuppliedPlanProvider({"task": plan()}), cases, run_workflow)
        self.assertEqual(cases, before)

    def test_baseline_commands_share_the_mutation_guard(self):
        workflow = {
            "run_id": "baseline",
            "dry_run": False,
            "steps": [
                {
                    "id": "repair",
                    "command": "mesh.remove_loose_vertices",
                    "params": {"object_name": "Fixture"},
                }
            ],
        }
        provider = SuppliedPlanProvider({"task": workflow})
        calls = []

        def runner(value):
            return calls.append(value) or {"status": "completed"}

        denied = evaluate(provider, [{"id": "task", "expected_status": "completed"}], runner)
        self.assertIn("allow_mutation", denied["cases"][0]["failures"][0])
        self.assertEqual(calls, [])
        allowed = evaluate(
            provider, [{"id": "task", "expected_status": "completed"}], runner, allow_mutation=True
        )
        self.assertTrue(allowed["passed"])
        workflow["steps"] = [{"id": "discover", "command": "capabilities", "params": {}}]
        self.assertTrue(
            evaluate(
                SuppliedPlanProvider({"task": workflow}),
                [{"id": "task", "expected_status": "completed"}],
                run_workflow,
            )["passed"]
        )

    def test_source_probe_detects_mutation_even_when_runner_raises(self):
        source = {"value": "original"}

        def probe(case):
            return hashlib.sha256(source["value"].encode()).hexdigest()

        def mutate(workflow):
            source["value"] = "changed"
            raise RuntimeError("after mutation")

        report = evaluate(
            SuppliedPlanProvider({"task": plan()}),
            [{"id": "task", "expected_status": "completed", "require_preservation": True}],
            mutate,
            source_probe=probe,
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["cases"][0]["source_preserved"])
        self.assertNotEqual(
            report["cases"][0]["source_before_sha256"], report["cases"][0]["source_after_sha256"]
        )

    def test_required_preservation_cannot_pass_without_a_probe(self):
        result = evaluate(
            SuppliedPlanProvider({"task": plan()}),
            [{"id": "task", "expected_status": "validated", "require_preservation": True}],
            run_workflow,
        )
        self.assertFalse(result["passed"])
        self.assertIsNone(result["cases"][0]["source_preserved"])

    def test_ranking_prefers_valid_preserved_nonregressing_candidate(self):
        class InvalidProvider:
            name = "invalid"

            def plan(self, task):
                return {"invalid": True}

        candidates = {
            name: SuppliedPlanProvider({"task": plan(name)}) for name in ("safe", "regressed")
        }
        candidates["invalid"] = InvalidProvider()
        candidates["changed"] = SuppliedPlanProvider({"task": plan("changed")})
        state = {"value": "original"}

        def runner(workflow):
            name = workflow["run_id"]
            if name == "changed":
                state["value"] = "changed"
            return {"status": "failed" if name == "regressed" else "completed"}

        report = providers.rank_candidates(
            candidates,
            [{"id": "task", "expected_status": "completed"}],
            runner,
            baseline={"schema_version": "1.0", "cases": [{"id": "task", "passed": True}]},
            source_probe=lambda case: hashlib.sha256(state["value"].encode()).hexdigest(),
            clock=lambda: 0,
        )
        self.assertEqual(
            [item["candidate_id"] for item in report["ranking"]],
            ["safe", "regressed", "changed", "invalid"],
        )
        self.assertTrue(report["ranking"][0]["eligible"])
        self.assertFalse(any(item["eligible"] for item in report["ranking"][1:]))
        self.assertEqual(report["artist_approval"], "not_evaluated")

    def test_cost_is_explicit_unknown_and_only_breaks_technical_latency_ties(self):
        candidates = {
            name: SuppliedPlanProvider({"task": plan(name)})
            for name in ("unknown", "expensive", "cheap")
        }
        costs = {
            "cheap": {"amount": 0.25, "currency": "USD", "evidence": "test ledger"},
            "expensive": {"amount": 2.0, "currency": "USD", "evidence": "test ledger"},
        }
        report = providers.rank_candidates(
            candidates,
            [{"id": "task", "expected_status": "validated"}],
            run_workflow,
            reported_costs=costs,
            source_probe=lambda case: "a" * 64,
            clock=lambda: 0,
        )
        self.assertEqual(
            [item["candidate_id"] for item in report["ranking"]], ["cheap", "expensive", "unknown"]
        )
        self.assertIsNone(report["ranking"][-1]["reported_cost"])
        self.assertEqual(report["ranking"][0]["reported_cost"], costs["cheap"])

    def test_unknown_preservation_never_becomes_eligible(self):
        report = providers.rank_candidates(
            {"candidate": SuppliedPlanProvider({"task": plan()})},
            [{"id": "task", "expected_status": "validated"}],
            run_workflow,
        )
        self.assertIsNone(report["ranking"][0]["source_preserved"])
        self.assertFalse(report["ranking"][0]["eligible"])

    def test_malformed_or_incomparable_costs_reject_before_execution(self):
        candidates = {name: SuppliedPlanProvider({"task": plan(name)}) for name in ("a", "b")}
        calls = []
        cases = [{"id": "task", "expected_status": "validated"}]
        costs = [
            {"a": {"amount": value, "currency": "USD", "evidence": "fixture"}}
            for value in (-1, True, float("nan"))
        ]
        costs.append(
            {
                "a": {"amount": 1, "currency": "USD", "evidence": "fixture"},
                "b": {"amount": 1, "currency": "EUR", "evidence": "fixture"},
            }
        )
        for cost in costs:
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                providers.rank_candidates(
                    candidates, cases, lambda p: calls.append(p), reported_costs=cost
                )
        self.assertEqual(calls, [])

    def test_versioned_snapshot_corpus_runs_actual_diagnostic_rules(self):
        path = Path(__file__).resolve().parents[1] / "benchmarks" / "evaluation-corpus.json"
        report = providers.evaluate_snapshot_corpus(path)
        self.assertTrue(report["passed"], report)
        self.assertGreaterEqual(report["metrics"]["total"], 6)
        self.assertTrue(all(case["source_preserved"] is True for case in report["cases"]))
        observed = {rule for case in report["cases"] for rule in case["rule_ids"]}
        self.assertTrue(
            {"DEGENERATE_FACES", "UNWEIGHTED_VERTICES", "MISSING_LIGHTING", "FRAME_RATE"}
            <= observed
        )
        self.assertEqual(report["artist_approval"], "not_evaluated")

    def test_corpus_wrong_expected_rule_is_a_failed_evaluation(self):
        path = Path(__file__).resolve().parents[1] / "benchmarks" / "evaluation-corpus.json"
        corpus = json.loads(path.read_text(encoding="utf-8"))
        corpus["fixtures"][0]["expected_rule_ids"] = ["INVENTED_RULE"]
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "corpus.json"
            altered.write_text(json.dumps(corpus), encoding="utf-8")
            report = providers.evaluate_snapshot_corpus(altered)
        self.assertFalse(report["passed"])
        self.assertIn("Expected diagnostic rule set differs", report["cases"][0]["failures"])

    def test_corpus_rejects_unsupported_schema_and_artist_assertion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            for value in (
                {
                    "schema_version": "2.0",
                    "corpus_id": "future",
                    "artist_approval": "not_evaluated",
                    "fixtures": [],
                },
                {
                    "schema_version": "1.0",
                    "corpus_id": "claimed",
                    "artist_approval": "accepted",
                    "fixtures": [],
                },
            ):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValueError):
                    providers.evaluate_snapshot_corpus(path)

    def test_corpus_hash_duplicate_keys_and_typed_fields_are_checked(self):
        path = Path(__file__).resolve().parents[1] / "benchmarks" / "evaluation-corpus.json"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            providers.evaluate_snapshot_corpus(path, expected_sha256="0" * 64)
        corpus = json.loads(path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "corpus.json"
            altered.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                providers.evaluate_snapshot_corpus(altered)
            for value in (True, -1, "8"):
                with self.subTest(value=value):
                    corpus["fixtures"][0]["scene"]["objects"][0]["vertex_count"] = value
                    altered.write_text(json.dumps(corpus), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        providers.evaluate_snapshot_corpus(altered)

    def test_invalid_preservation_evidence_does_not_authorize_runner(self):
        calls = []
        report = evaluate(
            SuppliedPlanProvider({"task": plan()}),
            [{"id": "task", "expected_status": "validated"}],
            lambda workflow: calls.append(workflow),
            source_probe=lambda case: "same",
        )
        self.assertFalse(report["passed"])
        self.assertEqual(calls, [])

    def test_latency_precedes_cost_when_technical_evidence_matches(self):
        candidates = {
            name: SuppliedPlanProvider({"task": plan(name)}) for name in ("faster", "cheaper")
        }
        ticks = iter([0, 1, 0, 2])
        report = providers.rank_candidates(
            candidates,
            [{"id": "task", "expected_status": "validated"}],
            run_workflow,
            source_probe=lambda case: "a" * 64,
            reported_costs={
                "faster": {"amount": 3, "currency": "USD", "evidence": "fixture"},
                "cheaper": {"amount": 1, "currency": "USD", "evidence": "fixture"},
            },
            clock=lambda: next(ticks),
        )
        self.assertEqual(
            [item["candidate_id"] for item in report["ranking"]], ["faster", "cheaper"]
        )

    def test_source_damage_stops_later_cases_and_candidates(self):
        candidates = {
            name: SuppliedPlanProvider({"first": plan(name), "later": plan(name + "-later")})
            for name in ("damaging", "untested")
        }
        state = {"value": "original"}
        calls = []

        def runner(workflow):
            calls.append(workflow["run_id"])
            state["value"] = "damaged"
            return {"status": "completed"}

        report = providers.rank_candidates(
            candidates,
            [{"id": identity, "expected_status": "completed"} for identity in ("first", "later")],
            runner,
            source_probe=lambda case: hashlib.sha256(state["value"].encode()).hexdigest(),
        )
        self.assertEqual(calls, ["damaging"])
        self.assertEqual(report["skipped_candidates"], ["untested"])
        self.assertFalse(report["evaluation_complete"])
        self.assertFalse(report["reports"]["damaging"]["cases"][1]["executed"])


if __name__ == "__main__":
    unittest.main()
