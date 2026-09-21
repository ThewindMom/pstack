from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pstack
import tasks


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source.mkdir()
        for name in ("poteto-mode", "setup-pstack", "how"):
            file = self.source / f"skills/{name}/SKILL.md"
            file.parent.mkdir(parents=True)
            file.write_text(f"---\nname: {name}\ndescription: Use when asked for {name}.\n---\n# Original\nKeep every mandatory step.\n")
        files = {"LICENSE": b"MIT fixture license", "assets/example.bin": bytes(range(256)),
                 "skills/poteto-mode/playbooks/feature.md": b"# Original feature\n1. Prove it.\n",
                 "skills/poteto-mode/scripts/tool.sh": b"#!/bin/sh\nprintf test\n"}
        for name, data in files.items():
            file = self.source / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        (self.source / "skills/poteto-mode/scripts/tool.sh").chmod(0o755)
        self.paths = sorted(str(p.relative_to(self.source)) for p in self.source.rglob("*") if p.is_file())
        self.wanted = pstack.payload(self.source, self.paths)

    def install(self):
        return pstack.apply(self.target, self.wanted)

    def test_preserves_every_source_byte(self):
        self.install()
        for name in self.paths:
            self.assertEqual((self.source / name).read_bytes(), (self.target / f".agents/pstack/upstream/{name}").read_bytes())
        self.assertEqual(pstack.doctor(self.target, False)["skills"], 3)
        self.assertEqual(pstack.doctor(self.target, False)["playbooks"], 1)

    def test_entry_points_have_capys_frontmatter_and_resolvable_links(self):
        self.install()
        for file in (self.target / ".agents/skills").glob("*/SKILL.md"):
            name, description = pstack.frontmatter(file.read_text())
            self.assertEqual(name, file.parent.name)
            self.assertTrue(description)
            for link in __import__("re").findall(r"\]\(([^)]+)\)", file.read_text()):
                self.assertTrue((file.parent / link).is_file(), link)
            self.assertNotIn("run_in_background", file.read_text())

    def test_setup_uses_native_override(self):
        wrapper = self.wanted[".agents/skills/setup-pstack/SKILL.md"][0].decode()
        self.assertIn("../../pstack/SETUP.md", wrapper)
        self.assertIn("instead of the Cursor setup", wrapper)

    def test_idempotent_install_preserves_mtime(self):
        self.install()
        before = {p: (self.target / p).stat().st_mtime_ns for p in self.wanted}
        report = self.install()
        self.assertEqual(report["write"], [])
        self.assertEqual(report["remove"], [])
        self.assertEqual(before, {p: (self.target / p).stat().st_mtime_ns for p in self.wanted})

    def test_preserves_existing_instructions_and_model_profile(self):
        self.target.mkdir()
        (self.target / "AGENTS.md").write_text("User instructions stay.")
        (self.target / ".agents").mkdir()
        (self.target / ".agents/pstack.models.json").write_text('{"max_parallel": 2}')
        self.install()
        self.assertEqual((self.target / "AGENTS.md").read_text(), "User instructions stay.")
        self.assertEqual((self.target / ".agents/pstack.models.json").read_text(), '{"max_parallel": 2}')

    def test_unmanaged_collision_refuses_entire_install(self):
        collision = self.target / ".agents/skills/how/SKILL.md"
        collision.parent.mkdir(parents=True)
        collision.write_text("My how skill")
        with self.assertRaisesRegex(pstack.PortError, "Unmanaged"):
            self.install()
        self.assertEqual(collision.read_text(), "My how skill")
        self.assertFalse((self.target / pstack.MANIFEST).exists())
        self.assertFalse((self.target / ".agents/pstack").exists())

    def test_local_edit_blocks_update_before_any_write(self):
        self.install()
        modified = self.target / ".agents/skills/how/SKILL.md"
        modified.write_text("Keep my edit")
        desired = dict(self.wanted)
        desired[".agents/pstack/new.md"] = (b"new", 0o644)
        with self.assertRaisesRegex(pstack.PortError, "was edited"):
            pstack.apply(self.target, desired)
        self.assertFalse((self.target / ".agents/pstack/new.md").exists())
        self.assertEqual(modified.read_text(), "Keep my edit")

    def test_uninstall_preserves_unmanaged_neighbors(self):
        self.install()
        neighbor = self.target / ".agents/skills/my-skill/SKILL.md"
        neighbor.parent.mkdir()
        neighbor.write_text("User skill")
        pstack.apply(self.target, {}, uninstall=True)
        self.assertEqual(neighbor.read_text(), "User skill")
        self.assertFalse((self.target / pstack.MANIFEST).exists())
        for name in self.wanted:
            self.assertFalse((self.target / name).exists())

    def test_uninstall_refuses_modified_owned_files(self):
        self.install()
        (self.target / ".agents/pstack/CAPY.md").write_text("Local change")
        with self.assertRaises(pstack.PortError):
            pstack.apply(self.target, {}, uninstall=True)
        self.assertTrue((self.target / pstack.MANIFEST).exists())

    def test_upgrade_removes_only_stale_managed_paths(self):
        self.install()
        wanted = dict(self.wanted)
        stale = ".agents/pstack/upstream/assets/example.bin"
        wanted.pop(stale)
        report = pstack.apply(self.target, wanted)
        self.assertEqual(report["remove"], [stale])
        self.assertFalse((self.target / stale).exists())
        self.assertEqual(report["write"], [])

    def test_dry_run_has_no_filesystem_effect(self):
        report = pstack.apply(self.target, self.wanted, dry_run=True)
        self.assertTrue(report["write"])
        self.assertFalse(self.target.exists())

    def test_modes_preserved_and_verified(self):
        self.install()
        script = self.target / ".agents/pstack/upstream/skills/poteto-mode/scripts/tool.sh"
        self.assertEqual(stat.S_IMODE(script.stat().st_mode), 0o755)
        script.chmod(0o644)
        with self.assertRaisesRegex(pstack.PortError, "mode changed"):
            pstack.doctor(self.target, False)

    def test_volume_layout_has_no_project_rules(self):
        wanted = pstack.payload(self.source, self.paths, volume=True)
        pstack.apply(self.target, wanted, volume=True)
        self.assertTrue((self.target / "skills/poteto-mode/SKILL.md").is_file())
        self.assertTrue((self.target / "pstack/CAPY.md").is_file())
        self.assertFalse((self.target / ".capy").exists())
        self.assertFalse((self.target / "AGENTS.md").exists())
        self.assertEqual(pstack.doctor(self.target, True)["skills"], 3)
        with self.assertRaises(pstack.PortError):
            pstack.doctor(self.target, False)

    def test_symlink_target_refused(self):
        actual = self.root / "actual"
        actual.mkdir()
        self.target.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(pstack.PortError, "symlink"):
            self.install()
        self.assertEqual(list(actual.iterdir()), [])

    def test_symlink_parent_refused(self):
        self.target.mkdir()
        actual = self.root / "actual"
        actual.mkdir()
        (self.target / ".agents").symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(pstack.PortError, "symlink"):
            self.install()
        self.assertEqual(list(actual.iterdir()), [])

    def test_source_symlink_refused(self):
        file = self.source / "link"
        file.symlink_to(self.source / "LICENSE")
        with self.assertRaisesRegex(pstack.PortError, "symlink"):
            pstack.payload(self.source, self.paths + ["link"])

    def test_path_traversal_rejected(self):
        for value in ("../escape", "/absolute", "a/../b", "a//b", "a\\b", "./a"):
            with self.subTest(value=value), self.assertRaises(pstack.PortError):
                pstack.safe_relative(value)
        with self.assertRaises(pstack.PortError):
            pstack.apply(self.target, {"README.md": (b"bad", 0o644)})

    def test_malicious_manifest_cannot_escape_target(self):
        self.target.mkdir()
        manifest = {"format": 1, "volume": False, "files": {"../outside": {"sha256": "0" * 64, "mode": 0o644}}}
        (self.target / pstack.MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaises(pstack.PortError):
            self.install()

    def test_live_lock_refuses_install(self):
        self.target.mkdir()
        (self.target / pstack.LOCK).write_text("locked")
        with self.assertRaisesRegex(pstack.PortError, "Another installation"):
            self.install()
        self.assertFalse((self.target / pstack.MANIFEST).exists())

    def test_exception_rolls_back_changed_files(self):
        self.install()
        before = {p: (self.target / p).read_bytes() for p in self.wanted}
        manifest = (self.target / pstack.MANIFEST).read_bytes()
        wanted = dict(self.wanted)
        wanted[".agents/pstack/CAPY.md"] = (b"update", 0o644)
        wanted[".agents/pstack/SETUP.md"] = (b"second update", 0o644)
        original = os.replace
        count = 0
        def fail_second(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated write failure")
            return original(src, dst)
        with patch.object(pstack.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                pstack.apply(self.target, wanted)
        self.assertEqual(before, {p: (self.target / p).read_bytes() for p in self.wanted})
        self.assertEqual(manifest, (self.target / pstack.MANIFEST).read_bytes())
        self.assertFalse((self.target / pstack.LOCK).exists())
        self.assertEqual(list(self.target.glob(".pstack-stage-*")), [])

    def test_missing_managed_file_fails_closed(self):
        self.install()
        (self.target / ".agents/pstack/CAPY.md").unlink()
        with self.assertRaisesRegex(pstack.PortError, "missing"):
            self.install()

    def test_missing_core_source_fails(self):
        with self.assertRaises(pstack.PortError):
            pstack.payload(self.source, [p for p in self.paths if "setup-pstack" not in p])

    def test_frontmatter_variants(self):
        name, desc = pstack.frontmatter("---\nname: 'Poteto Mode'\ndescription: >-\n  First line.\n  Second line.\n---\n")
        self.assertEqual((name, desc), ("Poteto Mode", "First line. Second line."))
        self.assertEqual(pstack.frontmatter('---\nname: how\ndescription: "A: B"\n---')[1], "A: B")
        for bad in ("none", "---\nname: x", "---\nname: x\n---"):
            with self.assertRaises(pstack.PortError):
                pstack.frontmatter(bad)


class TaskTests(unittest.TestCase):
    def task(self, name="api", **values):
        item = {"id": name, "repository": "owner/app", "role": "implementation", "goal": "Fix retry behavior",
                "write": True, "scope_paths": [f"src/{name}"], "base_ref": "main", "acceptance": ["Real test passes"]}
        item.update(values)
        return item

    def plan(self, *items, **values):
        return dict({"version": 1, "tasks": list(items) or [self.task()]}, **values)

    def result(self, name="api", **values):
        item = {"id": name, "native_task_id": f"task-{name}", "machine_id": f"machine-{name}", "status": "done",
                "base_sha": "a" * 40, "head_sha": "b" * 40, "branch": f"capy/{name}", "changed_paths": [f"src/{name}/file.py"],
                "evidence": [{"criterion": "Real test passes", "artifact": "artifacts/test-output.txt", "result": "pass"}]}
        item.update(values)
        return item

    def test_explicit_placement_and_parent_inheritance(self):
        plan = self.plan(self.task(), self.task("research", write=False, role="research"))
        before = copy.deepcopy(plan)
        prepared = tasks.prepare(plan)
        self.assertEqual([t["machine"] for t in prepared["tasks"]], ["fresh", "shared"])
        self.assertNotIn("model", prepared["tasks"][0])
        self.assertEqual(plan, before)
        self.assertIn("not an API request", prepared["dispatch"])

    def test_disjoint_writers_and_concurrency_waves(self):
        plan = self.plan(self.task("a"), self.task("b"), self.task("c"), max_parallel=2)
        self.assertEqual(tasks.prepare(plan)["waves"], [["a", "b"], ["c"]])

    def test_independent_overlap_rejected_even_with_concurrency_one(self):
        plan = self.plan(self.task("a", scope_paths=["src"]), self.task("b"), max_parallel=1)
        with self.assertRaisesRegex(tasks.PlanError, "Overlapping independent"):
            tasks.prepare(plan)

    def test_prefix_siblings_do_not_conflict(self):
        tasks.prepare(self.plan(self.task("api"), self.task("api2")))

    def test_same_path_in_distinct_repositories(self):
        tasks.prepare(self.plan(self.task("a", scope_paths=["src"]), self.task("b", repository="owner/other", scope_paths=["src"])))

    def test_stack_requires_branch_inheritance_not_just_order(self):
        dependent = self.task("b", scope_paths=["src/api"], depends_on=["api"])
        with self.assertRaisesRegex(tasks.PlanError, "must inherit"):
            tasks.prepare(self.plan(self.task(), dependent))
        dependent.pop("base_ref")
        dependent["base_from"] = "api"
        self.assertEqual(tasks.prepare(self.plan(self.task(), dependent))["waves"], [["api"], ["b"]])

    def test_review_of_fresh_writer_gets_its_branch_on_fresh_machine(self):
        review = self.task("review", role="review", write=False, depends_on=["api"], base_from="api")
        review.pop("base_ref")
        prepared = tasks.prepare(self.plan(self.task(), review))
        self.assertEqual(prepared["tasks"][1]["machine"], "fresh")

    def test_writer_cannot_share_machine(self):
        with self.assertRaisesRegex(tasks.PlanError, "fresh machine"):
            tasks.prepare(self.plan(self.task(machine="shared")))

    def test_readonly_role_cannot_write(self):
        for role in ("research", "review"):
            with self.assertRaises(tasks.PlanError):
                tasks.prepare(self.plan(self.task(role=role)))

    def test_shared_machine_cannot_claim_dependency_checkout(self):
        review = self.task("review", role="review", write=False, depends_on=["api"], base_from="api", machine="shared")
        review.pop("base_ref")
        with self.assertRaises(tasks.PlanError):
            tasks.prepare(self.plan(self.task(), review))

    def test_unconfirmed_model_rejected(self):
        with self.assertRaisesRegex(tasks.PlanError, "Unconfirmed model"):
            tasks.prepare(self.plan(self.task(model="cursor-only-model")))
        prepared = tasks.prepare(self.plan(self.task(model="observed-model"), confirmed_models=["observed-model"]))
        self.assertEqual(prepared["tasks"][0]["model"], "observed-model")

    def test_profile_and_task_override_precedence(self):
        profile = {"roles": {"implementation": "observed-a"}, "confirmed_models": ["observed-a", "observed-b"], "max_parallel": 2}
        plan = tasks.with_profile(self.plan(), profile)
        self.assertEqual(tasks.prepare(plan)["tasks"][0]["model"], "observed-a")
        self.assertEqual(tasks.prepare(plan)["max_parallel"], 2)
        plan = tasks.with_profile(self.plan(self.task(model="observed-b"), max_parallel=1), profile)
        self.assertEqual(tasks.prepare(plan)["tasks"][0]["model"], "observed-b")
        self.assertEqual(tasks.prepare(plan)["max_parallel"], 1)

    def test_depth_limit(self):
        self.assertEqual(tasks.prepare(self.plan(parent_depth=2))["tasks"][0]["child_depth"], 3)
        for depth in (3, -1, True):
            with self.assertRaises(tasks.PlanError):
                tasks.prepare(self.plan(parent_depth=depth))

    def test_invalid_dependencies_and_cycle(self):
        for deps in (["missing"], ["api"], ["missing", "missing"]):
            with self.assertRaises(tasks.PlanError):
                tasks.prepare(self.plan(self.task(depends_on=deps)))
        with self.assertRaisesRegex(tasks.PlanError, "cycle"):
            tasks.prepare(self.plan(self.task("a", depends_on=["b"]), self.task("b", depends_on=["a"])))

    def test_invalid_scopes_and_missing_acceptance(self):
        for scope in ("../x", "/tmp", "a//b", "a/../b", ".git/config", "src/*.py"):
            with self.assertRaises(tasks.PlanError):
                tasks.prepare(self.plan(self.task(scope_paths=[scope])))
        with self.assertRaises(tasks.PlanError):
            tasks.prepare(self.plan(self.task(acceptance=[])))

    def test_results_are_not_a_shipping_verdict(self):
        result = tasks.check_results(self.plan(), [self.result()])
        self.assertEqual(result["status"], "completion-evidence-present")
        self.assertFalse(result["safe_to_ship"])

    def test_idle_waiting_failed_are_not_success(self):
        for status in ("idle", "waiting", "working", "failed", "draft"):
            with self.assertRaisesRegex(tasks.PlanError, "not done"):
                tasks.check_results(self.plan(), [self.result(status=status)])

    def test_missing_failed_or_duplicate_evidence_rejected(self):
        for evidence in ([], [{"criterion": "Wrong test", "artifact": "x", "result": "pass"}],
                         [{"criterion": "Real test passes", "artifact": "x", "result": "fail"}]):
            with self.assertRaises(tasks.PlanError):
                tasks.check_results(self.plan(), [self.result(evidence=evidence)])

    def test_scope_escape_and_directory_claim_rejected(self):
        for files in (["src/api2/file.py"], ["../outside"], ["."]):
            with self.assertRaises(tasks.PlanError):
                tasks.check_results(self.plan(), [self.result(changed_paths=files)])

    def test_duplicate_native_task_ids_rejected(self):
        with self.assertRaisesRegex(tasks.PlanError, "distinct native_task_id"):
            tasks.check_results(self.plan(self.task("a"), self.task("b")),
                                [self.result("a"), self.result("b", native_task_id="task-a")])

    def test_stack_base_must_equal_predecessor_head(self):
        child = self.task("child", depends_on=["api"], base_from="api")
        child.pop("base_ref")
        plan = self.plan(self.task(), child)
        with self.assertRaisesRegex(tasks.PlanError, "predecessor commit"):
            tasks.check_results(plan, [self.result(), self.result("child")])
        tasks.check_results(plan, [self.result(), self.result("child", base_sha="b" * 40, head_sha="c" * 40)])

    def test_reader_cannot_report_edits_or_new_commit(self):
        plan = self.plan(self.task(write=False, role="review"))
        with self.assertRaises(tasks.PlanError):
            tasks.check_results(plan, [self.result(changed_paths=[])])
        with self.assertRaises(tasks.PlanError):
            tasks.check_results(plan, [self.result(head_sha="a" * 40)])
        tasks.check_results(plan, [self.result(changed_paths=[], head_sha="a" * 40)])

    def test_cli_example(self):
        process = subprocess.run([sys.executable, str(ROOT / "tools/tasks.py"), "prepare", str(ROOT / "examples/plan.json")], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["waves"], [["api", "docs"], ["review-api"]])


@unittest.skipUnless((ROOT / "_upstream/pstack/LICENSE").exists(), "Pinned submodule not initialized; integration runs in CI")
class RealUpstreamTests(unittest.TestCase):
    def test_full_upstream_install_and_every_source_hash(self):
        source, paths = pstack.checked_source()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            wanted = pstack.payload(source, paths)
            pstack.apply(target, wanted)
            report = pstack.doctor(target, False)
            self.assertGreaterEqual(report["skills"], 40)
            self.assertEqual(report["playbooks"], 23)
            for name in paths:
                self.assertEqual((source / name).read_bytes(), (target / f".agents/pstack/upstream/{name}").read_bytes())
            for file in (target / ".agents/skills").glob("*/SKILL.md"):
                for link in __import__("re").findall(r"\]\(([^)]+)\)", file.read_text()):
                    self.assertTrue((file.parent / link).is_file(), f"Broken entry point: {file}: {link}")
            self.assertEqual(pstack.apply(target, wanted)["write"], [])
            print("REAL_UPSTREAM_REPORT=" + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
