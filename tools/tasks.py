#!/usr/bin/env python3
"""Validate Capy task plans and evidence. This tool does not create or bill tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from itertools import combinations


class PlanError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def path(value: object) -> str:
    require(text(value), "Scope paths must be nonempty strings")
    assert isinstance(value, str)
    if value == ".":
        return value
    require(not value.startswith("/") and "\\" not in value and "\x00" not in value,
            f"Scope must be repository-relative: {value!r}")
    require(all(p not in ("", ".", "..", ".git") for p in value.split("/")), f"Unsafe scope: {value!r}")
    require(not any(c in value for c in "*?[]"), "Use concrete path prefixes, not globs")
    return value


def overlaps(a: str, b: str) -> bool:
    return a == "." or b == "." or a == b or a.startswith(b + "/") or b.startswith(a + "/")


def within(file: str, scope: str) -> bool:
    return scope == "." or file == scope or file.startswith(scope + "/")


def prepare(plan: dict) -> dict:
    require(isinstance(plan, dict), "Plan must be an object")
    require(plan.get("version") == 1, "Plan version must be 1")
    cap = plan.get("max_parallel", 3)
    depth = plan.get("parent_depth", 0)
    require(type(cap) is int and 1 <= cap <= 64, "max_parallel must be 1..64 (local safety limit)")
    require(type(depth) is int and 0 <= depth < 3, "Capy allows at most three child task levels")
    models = plan.get("confirmed_models", [])
    require(isinstance(models, list) and all(text(m) for m in models), "confirmed_models must be a list of observed model IDs")
    tasks = plan.get("tasks")
    require(isinstance(tasks, list) and bool(tasks), "Plan needs a nonempty tasks list")
    require(len(tasks) <= 256, "Split plans larger than 256 tasks into explicit runs")
    root = plan.get("pstack_root", ".agents/pstack")
    require(text(root), "pstack_root must identify the installed adapter")
    by_id = {}
    for original in tasks:
        require(isinstance(original, dict), "Task must be an object")
        task = dict(original)
        task_id = task.get("id")
        require(isinstance(task_id, str) and bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", task_id)), "Invalid task id")
        require(task_id not in by_id, f"Duplicate task: {task_id}")
        require(task.get("role") in ("implementation", "research", "design", "review", "comment-review"), f"Invalid role: {task_id}")
        require(text(task.get("repository")) and text(task.get("goal")), f"Task needs repository and goal: {task_id}")
        require(type(task.get("write")) is bool, f"Task must explicitly declare write: {task_id}")
        require(not (task["role"] in ("research", "review") and task["write"]), f"Read-only role cannot write: {task_id}")
        scopes = task.get("scope_paths", [])
        require(isinstance(scopes, list), f"scope_paths must be a list: {task_id}")
        task["scope_paths"] = [path(p) for p in scopes]
        require(bool(scopes) or not task["write"], f"Writer needs concrete scope_paths: {task_id}")
        criteria = task.get("acceptance")
        require(isinstance(criteria, list) and bool(criteria) and all(text(c) for c in criteria), f"Task needs acceptance criteria: {task_id}")
        require(len(criteria) == len(set(criteria)), f"Duplicate acceptance criterion: {task_id}")
        deps = task.get("depends_on", [])
        require(isinstance(deps, list) and all(text(d) for d in deps) and len(deps) == len(set(deps)), f"Invalid dependencies: {task_id}")
        task["depends_on"] = deps
        base_from = task.get("base_from")
        base_ref = task.get("base_ref")
        require(bool(text(base_from)) != bool(text(base_ref)), f"Set exactly one of base_ref or base_from: {task_id}")
        if base_from:
            require(base_from in deps, f"base_from must be an explicit dependency: {task_id}")
        machine = task.get("machine", "fresh" if task["write"] or base_from else "shared")
        require(machine in ("shared", "fresh"), f"Unknown machine placement: {task_id}")
        require(not task["write"] or machine == "fresh", f"Writer must use a fresh machine: {task_id}")
        require(not base_from or machine == "fresh", f"Dependent checkout needs a fresh machine: {task_id}")
        task["machine"] = machine
        model = task.get("model", "inherit-parent")
        require(model == "inherit-parent" or model in models, f"Unconfirmed model: {model!r}")
        task["model"] = model
        by_id[task_id] = task
    for task in by_id.values():
        for dep in task["depends_on"]:
            require(dep in by_id and dep != task["id"], f"Unknown or self dependency: {dep}")
        if task.get("base_from"):
            parent = by_id[task["base_from"]]
            require(parent["write"] and parent["repository"] == task["repository"], "base_from must be a writer in the same repository")
    ancestors: dict[str, set[str]] = {}
    pending = set(by_id)
    waves = []
    while pending:
        ready = sorted(i for i in pending if set(by_id[i]["depends_on"]) <= ancestors.keys())
        require(bool(ready), "Dependency cycle")
        batch = ready[:cap]
        waves.append(batch)
        for task_id in batch:
            deps = by_id[task_id]["depends_on"]
            ancestors[task_id] = set(deps).union(*(ancestors[d] for d in deps))
        pending.difference_update(batch)
    for left, right in combinations(by_id.values(), 2):
        if not left["write"] or not right["write"] or left["repository"] != right["repository"]:
            continue
        if left["id"] in ancestors[right["id"]] or right["id"] in ancestors[left["id"]]:
            continue
        require(not any(overlaps(a, b) for a in left["scope_paths"] for b in right["scope_paths"]),
                f"Overlapping independent writers: {left['id']} and {right['id']}. Stack them explicitly.")
    for task in by_id.values():
        for ancestor_id in ancestors[task["id"]]:
            ancestor = by_id[ancestor_id]
            if (task["write"] and ancestor["write"] and task["repository"] == ancestor["repository"]
                    and any(overlaps(a, b) for a in task["scope_paths"] for b in ancestor["scope_paths"])):
                # Ordering alone is insufficient: the descendant must inherit the earlier branch.
                chain = set()
                cursor = task.get("base_from")
                while cursor:
                    chain.add(cursor)
                    cursor = by_id[cursor].get("base_from")
                require(ancestor_id in chain, f"Overlapping stacked writer {task['id']} must inherit {ancestor_id}'s branch via base_from")
    prepared = []
    for task in by_id.values():
        task = dict(task)
        model = task.pop("model")
        if model != "inherit-parent":
            task["model"] = model
        task["child_depth"] = depth + 1
        task["brief"] = (f"Read {root}/CAPY.md before the relevant upstream workflow. "
                         f"Repository: {task['repository']}. Role: {task['role']}. Goal: {task['goal']}\n"
                         f"Placement must be {task['machine']}; verify the returned machine ID. "
                         f"Writable: {task['write']}. Scope: {json.dumps(task['scope_paths'])}.\n"
                         f"Acceptance: {json.dumps(task['acceptance'])}. Dependencies: {json.dumps(task['depends_on'])}.\n"
                         "Do not assume access to parent history or another machine's files. "
                         "Start only after dependencies are done and their evidence is accepted. Resolve base_from "
                         "to the predecessor's actual branch and commit before starting; verify that checkout. "
                         "Transfer required files with Capy's native transfer_files tool before use. "
                         "No push, PR creation, merge, deployment, or recurring automation without the caller's authorization. "
                         "Report native task ID, machine ID, status, base/head SHAs, branch, changed paths, "
                         "one evidence artifact and result per acceptance criterion, and remaining risks. "
                         "Idle is not done. Keep an existing live owner; do not launch a duplicate on timeout.")
        prepared.append(task)
    return {"version": 1, "max_parallel": cap, "waves": waves, "tasks": prepared,
            "dispatch": "Use the Capy agent's native task tools; this JSON is a work order, not an API request."}


def check_results(plan: dict, results: object) -> dict:
    prepared = prepare(plan)
    require(isinstance(results, list), "Results must be a list")
    by_id = {}
    native_ids = set()
    for item in results:
        require(isinstance(item, dict) and text(item.get("id")), "Invalid task result")
        require(item["id"] not in by_id, "Duplicate result ID")
        native_id = item.get("native_task_id")
        require(text(native_id) and native_id not in native_ids, "Each result needs a distinct native_task_id")
        native_ids.add(native_id)
        by_id[item["id"]] = item
    require(set(by_id) == {t["id"] for t in prepared["tasks"]}, "Missing or unexpected task results")
    for task in prepared["tasks"]:
        result = by_id[task["id"]]
        require(result.get("status") == "done", f"Task is not done: {task['id']}")
        require(text(result.get("machine_id")), "Missing machine_id")
        for name in ("base_sha", "head_sha"):
            require(isinstance(result.get(name), str) and bool(re.fullmatch(r"[0-9a-f]{40}", result[name])), f"Invalid {name}")
        require(task["write"] or result["base_sha"] == result["head_sha"], "Read-only task changed its commit")
        changed = result.get("changed_paths")
        require(isinstance(changed, list), "Missing changed_paths")
        require(task["write"] or not changed, "Read-only task reported edits")
        for name in changed:
            name = path(name)
            require(name != ".", "Report actual changed files, not the repository root")
            require(any(within(name, scope) for scope in task["scope_paths"]), f"Scope escape: {name}")
        if task["write"]:
            require(text(result.get("branch")), "Writer must report its actual branch")
        if task.get("base_from"):
            require(result["base_sha"] == by_id[task["base_from"]]["head_sha"], "Stack was not based on the reported predecessor commit")
        evidence = result.get("evidence")
        require(isinstance(evidence, list) and len(evidence) == len(task["acceptance"]), "Missing acceptance evidence")
        covered = []
        for item in evidence:
            require(isinstance(item, dict) and text(item.get("criterion")) and text(item.get("artifact")), "Invalid evidence")
            require(item.get("result") == "pass", "Acceptance criterion is not proven")
            covered.append(item["criterion"])
        require(sorted(covered) == sorted(task["acceptance"]), "Evidence must cover each criterion exactly once")
    return {"status": "completion-evidence-present", "tasks": len(by_id), "safe_to_ship": False,
            "next": "Inspect actual diffs and artifacts and obtain independent whole-PR review. This checker cannot authenticate evidence."}


def with_profile(plan: dict, profile: dict) -> dict:
    require(isinstance(plan, dict) and isinstance(profile, dict), "Plan and profile must be objects")
    roles = profile.get("roles", {})
    require(isinstance(roles, dict) and all(text(k) and text(v) for k, v in roles.items()), "Invalid role profile")
    merged = dict(plan)
    if "max_parallel" not in merged and "max_parallel" in profile:
        merged["max_parallel"] = profile["max_parallel"]
    if "confirmed_models" not in merged:
        merged["confirmed_models"] = profile.get("confirmed_models", [])
    tasks = merged.get("tasks")
    require(isinstance(tasks, list) and all(isinstance(t, dict) for t in tasks), "Invalid profile task list")
    merged["tasks"] = [dict(t, model=t.get("model", roles.get(t.get("role"), "inherit-parent"))) for t in tasks]
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "check-results"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--models", type=Path, help="Explicit adapter model profile")
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text())
        if args.models is not None:
            plan = with_profile(plan, json.loads(args.models.read_text()))
        if args.command == "check-results":
            require(args.results is not None, "--results is required")
            result = check_results(plan, json.loads(args.results.read_text()))
        else:
            result = prepare(plan)
        print(json.dumps(result, indent=2))
        return 0
    except (PlanError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"pstack tasks: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
