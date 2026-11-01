"""Local supplied-plan providers and technical evaluation, without model calls."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from types import UnionType
from typing import Protocol, get_args, get_origin, get_type_hints
from uuid import uuid4

from .commands import command_mutates
from .core import ObjectSnapshot, TextureSnapshot
from .provenance import canonical_json
from .workflows import validate_workflow


class PlanProvider(Protocol):
    name: str

    def plan(self, task: dict) -> dict: ...


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value)


class SuppliedPlanProvider:
    """Replay already supplied workflows; never generate or execute Python code."""

    name = "supplied_json"

    def __init__(self, plans: dict):
        if not isinstance(plans, dict) or not 1 <= len(plans) <= 100:
            raise ValueError("Provider requires 1..100 named plans")
        if len(canonical_json(plans).encode("utf-8")) > 1024 * 1024:
            raise ValueError("Provider plans exceed 1 MiB")
        for task_id, workflow in plans.items():
            if not _identifier(task_id):
                raise ValueError("Invalid provider task identity")
            validate_workflow(workflow)
        self._plans = deepcopy(plans)

    def plan(self, task: dict) -> dict:
        if not isinstance(task, dict) or set(task) - {"id", "context"} or "id" not in task:
            raise ValueError("Task requires id and optional context")
        if not _identifier(task["id"]) or task["id"] not in self._plans:
            raise ValueError("No supplied plan for this task identity")
        if not isinstance(task.get("context", {}), dict):
            raise ValueError("Task context must be a JSON object")
        canonical_json(task.get("context", {}))
        return deepcopy(self._plans[task["id"]])


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not permitted")
        result[key] = value
    return result


class FileReplayProvider(SuppliedPlanProvider):
    """Load one bounded snapshot of a local JSON corpus; no subsequent file reads."""

    name = "file_replay"

    def __init__(self, path: Path | str, *, expected_sha256: str | None = None):
        with Path(path).open("rb") as source:
            data = source.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("Provider file exceeds 1 MiB")
        self.source_sha256 = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and expected_sha256 != self.source_sha256:
            raise ValueError("Provider file hash does not match the expected source")
        corpus = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
        if not isinstance(corpus, dict) or set(corpus) != {"schema_version", "plans"}:
            raise ValueError("Provider file requires exactly schema_version and plans")
        if corpus["schema_version"] != "1.0":
            raise ValueError("Unsupported provider schema_version")
        super().__init__(corpus["plans"])


def _cases(cases):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError("Evaluation requires 1..100 cases")
    ids = set()
    for case in cases:
        allowed = {
            "id",
            "context",
            "expected_status",
            "required_commands",
            "required_rule_ids",
            "max_error_findings",
            "max_seconds",
            "expected_rule_ids",
            "require_preservation",
        }
        if (
            not isinstance(case, dict)
            or not {"id", "expected_status"} <= case.keys()
            or set(case) - allowed
        ):
            raise ValueError("Case has missing or unknown fields")
        if not _identifier(case["id"]) or case["id"] in ids:
            raise ValueError("Case identities must be valid and unique")
        ids.add(case["id"])
        if not isinstance(case["expected_status"], str) or case["expected_status"] not in {
            "validated",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError("Unsupported expected workflow status")
        if not isinstance(case.get("context", {}), dict):
            raise ValueError("Case context must be a JSON object")
        for field in ("required_commands", "required_rule_ids", "expected_rule_ids"):
            value = case.get(field, [])
            if (
                not isinstance(value, list)
                or not all(isinstance(item, str) and item for item in value)
                or len(set(value)) != len(value)
            ):
                raise ValueError(f"{field} must be an array of unique strings")
        if type(case.get("require_preservation", False)) is not bool:
            raise ValueError("require_preservation must be a boolean")
        errors = case.get("max_error_findings", 0)
        if type(errors) is not int or errors < 0:
            raise ValueError("max_error_findings must be a nonnegative integer")
        if "max_seconds" in case and (
            type(case["max_seconds"]) not in {int, float} or not 0 < case["max_seconds"] <= 3600
        ):
            raise ValueError("max_seconds must be positive and no greater than 3600")
    if len(canonical_json(cases).encode("utf-8")) > 1024 * 1024:
        raise ValueError("Evaluation cases exceed 1 MiB")


def _observations(value):
    rules = set()
    errors = 0

    def visit(item):
        nonlocal errors
        if isinstance(item, dict):
            if isinstance(item.get("rule_id"), str):
                rules.add(item["rule_id"])
                errors += item.get("severity") == "ERROR"
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return rules, errors


def evaluate(
    provider: PlanProvider,
    cases: list,
    runner,
    *,
    baseline=None,
    allow_mutation=False,
    source_probe=None,
    clock=time.perf_counter,
) -> dict:
    """Run explicit technical expectations against a caller-supplied runner.

    The runner is trusted application code, never supplied as executable text.
    Applied workflows containing mutating commands require allow_mutation=True.
    This is a regression harness, not a measurement of artistic acceptance.
    """
    _cases(cases)
    if type(allow_mutation) is not bool or not callable(runner):
        raise ValueError("A callable runner and boolean allow_mutation are required")
    if source_probe is not None and not callable(source_probe):
        raise ValueError("source_probe must be callable or None")
    old = {}
    if baseline is not None:
        if (
            not isinstance(baseline, dict)
            or baseline.get("schema_version") != "1.0"
            or not isinstance(baseline.get("cases"), list)
        ):
            raise ValueError("Baseline must be a versioned evaluation report")
        for case in baseline["cases"]:
            if (
                not isinstance(case, dict)
                or not _identifier(case.get("id"))
                or type(case.get("passed")) is not bool
                or case["id"] in old
            ):
                raise ValueError("Baseline case identities and outcomes are invalid")
            old[case["id"]] = case["passed"]
    outcomes = []
    preservation_stop = False
    for case in deepcopy(cases):
        if preservation_stop:
            outcomes.append(
                {
                    "id": case["id"],
                    "passed": False,
                    "executed": False,
                    "plan_valid": False,
                    "source_preserved": None,
                    "error_findings": 0,
                    "rule_ids": [],
                    "elapsed_seconds": 0,
                    "failures": ["Not run after source preservation failed"],
                }
            )
            continue
        started = clock()
        outcome = {
            "id": case["id"],
            "passed": False,
            "failures": [],
            "error_findings": 0,
            "rule_ids": [],
            "plan_valid": False,
            "source_preserved": None,
            "executed": False,
        }
        try:
            workflow = provider.plan({"id": case["id"], "context": case.get("context", {})})
            validate_workflow(workflow)
            outcome["plan_valid"] = True
            outcome["plan_sha256"] = hashlib.sha256(canonical_json(workflow).encode()).hexdigest()
            commands = {step["command"] for step in workflow["steps"]}
            if (
                not allow_mutation
                and workflow.get("dry_run", True) is False
                and any(
                    command_mutates(step["command"]) and step["params"].get("dry_run") is not True
                    for step in workflow["steps"]
                )
            ):
                raise ValueError("Applied evaluation requires explicit allow_mutation=True")
            if source_probe is not None:
                outcome["source_before_sha256"] = _source_hash(source_probe(deepcopy(case)))
            try:
                outcome["executed"] = True
                result = runner(deepcopy(workflow))
            finally:
                if "source_before_sha256" in outcome:
                    outcome["source_after_sha256"] = _source_hash(source_probe(deepcopy(case)))
                    outcome["source_preserved"] = (
                        outcome["source_before_sha256"] == outcome["source_after_sha256"]
                    )
                    if not outcome["source_preserved"]:
                        outcome["failures"].append("Source fingerprint changed during evaluation")
            if not isinstance(result, dict):
                raise ValueError("Runner must return a workflow result object")
            serialized = canonical_json(result)
            outcome["result_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
            outcome["status"] = result.get("status")
            rules, error_count = _observations(result)
            outcome.update(error_findings=error_count, rule_ids=sorted(rules))
            if result.get("status") != case["expected_status"]:
                outcome["failures"].append("Unexpected workflow status")
            if set(case.get("required_commands", [])) - commands:
                outcome["failures"].append("Required commands are missing from the supplied plan")
            if set(case.get("required_rule_ids", [])) - rules:
                outcome["failures"].append("Required diagnostic rules were not observed")
            if "expected_rule_ids" in case and set(case["expected_rule_ids"]) != rules:
                outcome["failures"].append("Expected diagnostic rule set differs")
            if error_count > case.get("max_error_findings", 0):
                outcome["failures"].append("Error findings exceed the case expectation")
        except Exception as error:
            outcome["error_type"] = type(error).__name__
            outcome["failures"].append(str(error)[:500])
        outcome["elapsed_seconds"] = max(0, clock() - started)
        if case.get("require_preservation", False) and outcome["source_preserved"] is not True:
            outcome["failures"].append("Required source preservation was not verified")
        if "max_seconds" in case and outcome["elapsed_seconds"] > case["max_seconds"]:
            outcome["failures"].append("Elapsed time exceeded the case budget")
        outcome["passed"] = not outcome["failures"]
        if (
            outcome["executed"]
            and source_probe is not None
            and outcome["source_preserved"] is not True
        ):
            preservation_stop = True
        outcomes.append(outcome)
    regressions = sorted(
        item["id"] for item in outcomes if old.get(item["id"]) is True and not item["passed"]
    )
    improvements = sorted(
        item["id"] for item in outcomes if old.get(item["id"]) is False and item["passed"]
    )
    removed = sorted(set(old) - {item["id"] for item in outcomes})
    successes = sum(item["passed"] for item in outcomes)
    return {
        "schema_version": "1.0",
        "provider": provider.name,
        "passed": successes == len(outcomes) and not removed,
        "cases": outcomes,
        "regressions": regressions,
        "improvements": improvements,
        "removed_cases": removed,
        "artist_approval": "not_evaluated",
        "stopped_for_source_preservation": preservation_stop,
        "metrics": {
            "total": len(outcomes),
            "successes": successes,
            "success_rate": successes / len(outcomes),
            "regression_count": len(regressions),
            "improvement_count": len(improvements),
            "mean_seconds": sum(item["elapsed_seconds"] for item in outcomes) / len(outcomes),
        },
    }


def _source_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Source probe must return a lowercase SHA256 of the measured source")
    return value


def rank_candidates(
    candidates,
    cases,
    runner,
    *,
    baseline=None,
    source_probe=None,
    reported_costs=None,
    allow_mutation=False,
    clock=time.perf_counter,
):
    """Evaluate offline candidates, then rank technical evidence lexicographically.

    The runner and source probe are trusted host code. No candidate is applied by
    this ranking function beyond explicitly authorized evaluation. A null cost is
    unknown, never free. Reported currencies must match; no exchange rates inferred.
    """
    if not isinstance(candidates, dict) or not 1 <= len(candidates) <= 20:
        raise ValueError("Ranking requires 1..20 candidate providers")
    if any(
        not _identifier(identity) or not callable(getattr(provider, "plan", None))
        for identity, provider in candidates.items()
    ):
        raise ValueError("Candidate identities and provider plan methods are required")
    _cases(cases)
    costs = {} if reported_costs is None else deepcopy(reported_costs)
    if not isinstance(costs, dict) or costs.keys() - candidates.keys():
        raise ValueError("Costs may identify only evaluated candidates")
    currencies = set()
    for value in costs.values():
        if value is None:
            continue
        if not isinstance(value, dict) or set(value) != {"amount", "currency", "evidence"}:
            raise ValueError("Reported cost requires amount, currency and evidence")
        if (
            type(value["amount"]) not in (int, float)
            or not math.isfinite(value["amount"])
            or value["amount"] < 0
        ):
            raise ValueError("Reported cost amount must be finite and nonnegative")
        if not isinstance(value["currency"], str) or not re.fullmatch(
            r"[A-Z]{3}", value["currency"]
        ):
            raise ValueError("Reported cost currency must be a three-letter uppercase code")
        if (
            not isinstance(value["evidence"], str)
            or not 1 <= len(value["evidence"].strip()) <= 4096
        ):
            raise ValueError("Reported cost needs an evidence description")
        currencies.add(value["currency"])
    if len(currencies) > 1:
        raise ValueError(
            "Different currencies cannot be ranked without an explicit common accounting basis"
        )
    ranking, reports, skipped = [], {}, []
    preservation_stop = False
    for identity, provider in candidates.items():
        if preservation_stop:
            skipped.append(identity)
            continue
        report = evaluate(
            provider,
            cases,
            runner,
            baseline=baseline,
            source_probe=source_probe,
            allow_mutation=allow_mutation,
            clock=clock,
        )
        reports[identity] = report
        preservation_stop = report["stopped_for_source_preservation"]
        preserved = [item["source_preserved"] for item in report["cases"]]
        source_preserved = (
            False
            if False in preserved
            else True
            if all(value is True for value in preserved)
            else None
        )
        valid = all(item["plan_valid"] for item in report["cases"])
        regressions = len(report["regressions"]) + len(report["removed_cases"])
        ranking.append(
            {
                "candidate_id": identity,
                "plans_valid": valid,
                "source_preserved": source_preserved,
                "regression_count": regressions,
                "successes": report["metrics"]["successes"],
                "mean_seconds": report["metrics"]["mean_seconds"],
                "reported_cost": costs.get(identity),
                "eligible": valid
                and source_preserved is True
                and regressions == 0
                and report["passed"],
            }
        )

    def key(item):
        cost = item["reported_cost"]
        return (
            not item["plans_valid"],
            0 if item["source_preserved"] is True else 1 if item["source_preserved"] is None else 2,
            item["regression_count"],
            -item["successes"],
            item["mean_seconds"],
            cost is None,
            cost["amount"] if cost else 0,
            item["candidate_id"],
        )

    ranking.sort(key=key)
    for index, item in enumerate(ranking, 1):
        item["rank"] = index
    return {
        "schema_version": "1.0",
        "ranking": ranking,
        "reports": reports,
        "skipped_candidates": skipped,
        "evaluation_complete": not preservation_stop,
        "ranking_policy": [
            "plans_valid",
            "source_preserved",
            "fewest_regressions",
            "most_successes",
            "lowest_measured_latency",
            "lowest_reported_comparable_cost",
            "candidate_id",
        ],
        "artist_approval": "not_evaluated",
        "automatic_application": False,
    }


def _snapshot_value(value, kind):
    """Strictly decode the frozen snapshot types; no runtime class names from JSON."""
    origin, args = get_origin(kind), get_args(kind)
    if origin is UnionType:
        for choice in args:
            try:
                return _snapshot_value(value, choice)
            except (TypeError, ValueError):
                pass
        raise ValueError("Snapshot union field has an invalid type")
    if origin is tuple:
        if not isinstance(value, list) or len(value) > 1000:
            raise ValueError("Snapshot tuple field requires a bounded JSON array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_snapshot_value(item, args[0]) for item in value)
        if len(value) != len(args):
            raise ValueError("Snapshot tuple field has an invalid length")
        return tuple(
            _snapshot_value(item, expected) for item, expected in zip(value, args, strict=True)
        )
    if is_dataclass(kind):
        if not isinstance(value, dict) or value.keys() - {field.name for field in fields(kind)}:
            raise ValueError("Snapshot has unknown fields or invalid type")
        hints = get_type_hints(kind)
        if any(
            type(item) is int
            and item < 0
            and (kind in (ObjectSnapshot, TextureSnapshot) or name == "light_count")
            for name, item in value.items()
        ):
            raise ValueError("Snapshot counts must be nonnegative")
        try:
            return kind(
                **{name: _snapshot_value(item, hints[name]) for name, item in value.items()}
            )
        except TypeError as error:
            raise ValueError("Snapshot is missing required fields") from error
    if kind is float and type(value) in (int, float) and math.isfinite(value):
        return value
    if kind in (str, int, bool, type(None)) and type(value) is kind:
        return value
    raise ValueError("Snapshot field has an invalid type")


def evaluate_snapshot_corpus(path, *, expected_sha256=None, clock=time.perf_counter):
    """Replay bounded synthetic snapshots through the actual scene.validate API.

    The corpus records expected diagnostic failures, not desired artistic labels.
    Fresh workflow IDs prevent a previous run's replay cache from skipping checks.
    """
    from .api import dispatch
    from .core import PROFILES, SceneSnapshot
    from .workflows import run_workflow

    with Path(path).open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Evaluation corpus exceeds 1 MiB")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        raise ValueError("Evaluation corpus hash mismatch")
    corpus = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    if not isinstance(corpus, dict) or set(corpus) != {
        "schema_version",
        "corpus_id",
        "artist_approval",
        "fixtures",
    }:
        raise ValueError("Invalid evaluation corpus envelope")
    if (
        corpus["schema_version"] != "1.0"
        or not _identifier(corpus["corpus_id"])
        or corpus["artist_approval"] != "not_evaluated"
    ):
        raise ValueError("Unsupported corpus schema or artist assertion")
    if not isinstance(corpus["fixtures"], list) or not 1 <= len(corpus["fixtures"]) <= 100:
        raise ValueError("Evaluation corpus requires 1..100 fixtures")
    canonical_json(corpus)
    snapshots, plans, cases, run_ids = {}, {}, [], {}
    generation = uuid4().hex
    for index, fixture in enumerate(corpus["fixtures"]):
        if not isinstance(fixture, dict) or set(fixture) != {
            "id",
            "scene",
            "profile",
            "expected_rule_ids",
            "expected_passed",
            "expected_error_count",
        }:
            raise ValueError("Invalid evaluation fixture fields")
        identity = fixture["id"]
        if not _identifier(identity) or identity in snapshots:
            raise ValueError("Fixture identities must be valid and unique")
        if (
            not isinstance(fixture["profile"], str)
            or fixture["profile"] not in PROFILES
            or type(fixture["expected_passed"]) is not bool
        ):
            raise ValueError("Invalid fixture profile or pass expectation")
        snapshots[identity] = _snapshot_value(fixture["scene"], SceneSnapshot)
        run_id = f"corpus-{generation}-{index}"
        run_ids[run_id] = identity
        plans[identity] = {
            "run_id": run_id,
            "dry_run": False,
            "steps": [
                {
                    "id": "inspect",
                    "command": "scene.validate",
                    "params": {"profile": fixture["profile"]},
                    "require": [
                        {"path": "result.passed", "equals": fixture["expected_passed"]},
                        {"path": "result.counts.ERROR", "equals": fixture["expected_error_count"]},
                    ],
                }
            ],
        }
        cases.append(
            {
                "id": identity,
                "expected_status": "completed",
                "required_commands": ["scene.validate"],
                "expected_rule_ids": fixture["expected_rule_ids"],
                "max_error_findings": fixture["expected_error_count"],
                "require_preservation": True,
            }
        )

    class Adapter:
        def __init__(self, snapshot):
            self.snapshot = snapshot

        def capture_scene(self):
            return self.snapshot

    def runner(workflow):
        adapter = Adapter(snapshots[run_ids[workflow["run_id"]]])
        return run_workflow(workflow, dispatch_fn=lambda request: dispatch(request, adapter))

    report = evaluate(
        SuppliedPlanProvider(plans),
        cases,
        runner,
        source_probe=lambda case: hashlib.sha256(
            canonical_json(
                json.loads(json.dumps(asdict(snapshots[case["id"]]), allow_nan=False))
            ).encode()
        ).hexdigest(),
        clock=clock,
    )
    return {
        **report,
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": digest,
        "fixture_kind": "synthetic_structural_snapshots",
    }
