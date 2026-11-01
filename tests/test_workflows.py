import unittest

from framewright.workflows import clear_run_cache, run_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        clear_run_cache()
        self.calls = []

    def run_step(self, request):
        self.calls.append(request)
        return {"ok": True, "result": {"plan_token": "token", "source_fingerprint": "fingerprint"}}

    def plan(self, **kwargs):
        return {
            "run_id": "test",
            "steps": [
                {
                    "id": "plan",
                    "command": "repair.plan_remove_loose",
                    "params": {"object_name": "Prop"},
                },
                {
                    "id": "apply",
                    "command": "repair.apply_plan",
                    "params": {
                        "plan_token": {"$ref": "plan.result.plan_token"},
                        "source_fingerprint": {"$ref": "plan.result.source_fingerprint"},
                    },
                },
            ],
            **kwargs,
        }

    def test_default_preview_runs_nothing(self):
        result = run_workflow(self.plan(), dispatch_fn=self.run_step)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.calls, [])

    def test_explicit_run_resolves_prior_outputs_and_applies(self):
        result = run_workflow(self.plan(dry_run=False), dispatch_fn=self.run_step)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.calls[1]["params"]["plan_token"], "token")
        self.assertIs(self.calls[1]["params"]["dry_run"], False)

    def test_replay_returns_prior_result_without_repeating_edits(self):
        run_workflow(self.plan(dry_run=False), dispatch_fn=self.run_step)
        result = run_workflow(self.plan(dry_run=False), dispatch_fn=self.run_step)
        self.assertTrue(result["replayed"])
        self.assertEqual(len(self.calls), 2)
        changed = self.plan(dry_run=False)
        changed["steps"][0]["params"]["object_name"] = "Other"
        with self.assertRaises(ValueError):
            run_workflow(changed, dispatch_fn=self.run_step)

    def test_unknown_later_command_rejects_before_first_step(self):
        plan = self.plan(dry_run=False)
        plan["steps"][1]["command"] = "python.exec"
        with self.assertRaises(ValueError):
            run_workflow(plan, dispatch_fn=self.run_step)
        self.assertEqual(self.calls, [])

    def test_forward_refs_and_recursive_workflows_rejected(self):
        for command in ["workflow.run", "repair.apply_plan"]:
            plan = self.plan()
            plan["steps"][0]["command"] = command
            plan["steps"][0]["params"] = {
                "plan_token": {"$ref": "apply.result.token"},
                "source_fingerprint": "x",
            }
            with self.assertRaises(ValueError):
                run_workflow(plan)

    def test_failure_stops_subsequent_steps_and_is_recorded(self):
        def fail(request):
            self.calls.append(request)
            return {"ok": False, "error": {"code": "OPERATION_REJECTED", "message": "fixture"}}

        result = run_workflow(self.plan(dry_run=False), dispatch_fn=fail)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.calls), 1)

    def test_cancel_before_step_leaves_no_edits(self):
        result = run_workflow(
            self.plan(dry_run=False), dispatch_fn=self.run_step, cancelled=lambda: True
        )
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.calls, [])

    def test_baseline_commands_can_follow_a_mutating_step(self):
        plan = self.plan(dry_run=False)
        plan["steps"].extend(
            [
                {
                    "id": "check",
                    "command": "scene.validate",
                    "params": {"profile": "studio_static"},
                },
                {"id": "inspect", "command": "scene.inspect", "params": {}},
            ]
        )
        result = run_workflow(plan, dispatch_fn=self.run_step)
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("dry_run", self.calls[-1]["params"])

    def test_capabilities_executes_and_legacy_repair_declares_scene_effect(self):
        result = run_workflow(
            {
                "run_id": "cap",
                "dry_run": False,
                "steps": [{"id": "discover", "command": "capabilities", "params": {}}],
            }
        )
        self.assertEqual(result["status"], "completed")
        self.assertIn("profiles", result["steps"][0]["response"]["result"])
        result = run_workflow(
            {
                "run_id": "legacy",
                "steps": [
                    {
                        "id": "repair",
                        "command": "mesh.remove_loose_vertices",
                        "params": {"object_name": "Prop"},
                    }
                ],
            }
        )
        self.assertEqual(result["steps"][0]["effect"], "scene")

    def test_invalid_validation_profile_rejected_before_mutation(self):
        plan = self.plan(dry_run=False)
        plan["steps"].append(
            {"id": "bad", "command": "scene.validate", "params": {"profile": "made_up"}}
        )
        with self.assertRaises(ValueError):
            run_workflow(plan, dispatch_fn=self.run_step)
        self.assertEqual(self.calls, [])

    def test_failed_technical_gate_prevents_following_edit(self):
        plan = self.plan(dry_run=False)
        plan["steps"][0] = {
            "id": "check",
            "command": "scene.validate",
            "params": {},
            "require": [{"path": "result.passed", "equals": True}],
        }
        plan["steps"][1] = {"id": "build", "command": "model.build_prop", "params": {}}

        def failed_check(request):
            self.calls.append(request)
            return {"ok": True, "result": {"passed": False}}

        result = run_workflow(plan, dispatch_fn=failed_check)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["steps"][0]["gate_failure"]["actual"], False)

    def test_gate_passes_strict_types_and_unknown_paths_fail_closed(self):
        for actual, expected_status in [(True, "completed"), (1, "failed"), (None, "failed")]:
            clear_run_cache()
            result = run_workflow(
                {
                    "run_id": "gated",
                    "dry_run": False,
                    "steps": [
                        {
                            "id": "check",
                            "command": "scene.validate",
                            "params": {},
                            "require": [{"path": "result.passed", "equals": True}],
                        }
                    ],
                },
                dispatch_fn=lambda request, actual=actual: {
                    "ok": True,
                    "result": {} if actual is None else {"passed": actual},
                },
            )
            self.assertEqual(result["status"], expected_status)

    def test_gate_shape_rejected_before_any_step(self):
        plan = self.plan(dry_run=False)
        plan["steps"][1]["require"] = [{"path": "__class__", "evaluate": "code"}]
        with self.assertRaises(ValueError):
            run_workflow(plan, dispatch_fn=self.run_step)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
