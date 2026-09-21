# pstack for Capy

A Capy-native adaptation of Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/640ea3abfbdef74aad432b58d8586e4bf645f42d/pstack), version 0.15.2. It preserves the complete upstream workflows, playbooks, principles, supporting files, and MIT license while translating execution to Capy skills, tasks, machines, volumes, and authorized automations.

This implementation lives on **`ThewindMom/pstack`, branch `capy-port`**. The existing `main` branch and the separate [Grok](https://github.com/ThewindMom/grok-pstack) and [Amp](https://github.com/ThewindMom/amp-pstack) ports are unchanged.

## What is different from the Cursor plugin

This is a native skill bundle and an executable adapter, not a Cursor process inside Capy or an invented Capy plugin SDK.

- **Progressive loading.** Each skill has a small `.agents/skills/<name>/SKILL.md` entry. Capy reads the adapter and the requested full upstream workflow on demand. There is no giant always-loaded prompt.
- **Task and machine ownership.** Use shared machines for readers of the current checkout and fresh machines for writers. Work orders check disjoint writable scopes, dependency cycles, nesting depth, parallelism, and explicit branch inheritance for stacks. Native task IDs remain the source of lifecycle truth.
- **Real handoffs.** Children get self-contained briefs. Cross-machine files travel through Capy's native `transfer_files`, not an assumed shared filesystem. Fresh machines must have the installed skills or an attached skill volume before starting dependent work.
- **Evidence, not a done-shaped summary.** Result validation requires completed native tasks, actual base/head commits, scoped changed paths, and a passing artifact for each acceptance criterion. Idle is not done. This is not a shipping approval; independent whole-PR review still applies.
- **Capy models and persistence.** Defaults inherit the parent model. Explicit model choices must be available in the actual session. Durable state belongs in a selected volume or an authorized pushed commit, not an ephemeral machine's home directory. Long-running workflows use authorized native tasks and automations, not detached cron loops.

The source is deliberately not rewritten with global string replacements. That would risk deleting mandatory steps, changing exceptions, or breaking relative script paths. Generated entry points read [the controlling Capy adapter](adapter/CAPY.md) and then the byte-preserved workflow. `setup-pstack` instead uses [Capy-specific setup](adapter/SETUP.md). Cursor tools, model names, storage paths, and source autonomy language never grant Capy capabilities or permissions.

## Install into a project

Requires Git and Python **3.10 or later**. The installer has no third-party Python dependencies and performs no network requests, task creation, pushes, or package installation.

```bash
git clone --branch capy-port --recurse-submodules \
  https://github.com/ThewindMom/pstack.git pstack-capy
cd pstack-capy

python3 tools/pstack.py install --target /path/to/your-project --dry-run
python3 tools/pstack.py install --target /path/to/your-project
python3 tools/pstack.py doctor --target /path/to/your-project
```

For an existing clone without its source submodule:

```bash
git submodule update --init --depth 1 _upstream
```

The installer verifies the exact upstream commit **`640ea3abfbdef74aad432b58d8586e4bf645f42d`** and refuses modified source. The generated project layout is:

```text
.agents/skills/<skill>/SKILL.md       Native Capy entries for all source skills
.agents/pstack/CAPY.md               Platform translation and execution contract
.agents/pstack/SETUP.md              Capy model and workflow configuration
.agents/pstack/tasks.py              Work-order and evidence checker
.agents/pstack/upstream/             Complete byte-preserved pstack subtree
.agents/pstack/provenance.json       Source revision, inventory, per-file hashes
.capy/rules/pstack-capy.mdc           Small, always-applied opt-in routing rule
.pstack-capy-manifest.json           Installer ownership and integrity information
```

`AGENTS.md`, unrelated skills, and user configuration are not overwritten. Existing conflicting skills stop the whole operation before any managed file is changed. There is no force-overwrite option. Choose an unambiguous installation scope or explicitly reconcile the existing skill yourself.

Make the generated files available to the project's Capy checkout. For fresh machines, use a caller-authorized commit/push of the installed files or attach the intended persistent skill volume. A clone of this port elsewhere on a machine is not automatically visible to every task. Do not publish private project files merely to transfer them.

## Install on an attached volume

Use the **actual mounted volume root** shown by your Capy session. No home-directory convention is assumed.

```bash
python3 tools/pstack.py install --volume --target /actual/mounted/volume --dry-run
python3 tools/pstack.py install --volume --target /actual/mounted/volume
python3 tools/pstack.py doctor --volume --target /actual/mounted/volume
```

This writes `skills/<skill>/SKILL.md` and `pstack/` at that root, not `.agents/skills`. It does not replace volume instructions. Attach the volume to the intended thread/tasks. Capy's documented discovery rules decide precedence; do not keep conflicting copies or assume both implementations of a same-named skill will run. See [Capy skills](https://docs.capy.ai/skills).

## Use it

After installing, start a Capy thread with the project or selected volume attached. Ask:

```text
Use setup-pstack to configure this Capy installation.
Then use poteto-mode to reproduce the export retry bug, fix its root cause,
and verify the actual export. Use native tasks for independent work.
```

No provider override is required. The source's slash-prefixed names are workflow names; this port does not claim to register a separate Capy command palette or mode dial.

The bootstrap skill in this port's own `.agents/skills/pstack-capy/` helps an agent install the pinned bundle. It is not the full installed catalog.

## Work orders and model roles

Copy [examples/plan.json](examples/plan.json) and replace its repository, goals, scopes, and acceptance criteria. It demonstrates two independent writers and a reviewer that starts from the implementation's actual branch.

```bash
python3 /path/to/your-project/.agents/pstack/tasks.py prepare plan.json
```

For a volume installation, run `python3 /actual/mounted/volume/pstack/tasks.py` and set `pstack_root` in the plan to that installed directory. The output is **a work order for the native agent**, not a payload to POST to an API. The coordinator must draft/start tasks using its real Capy tools and verify actual machine placement, model availability, ownership, and live-task counts.

Dependent writers that touch overlapping paths require both `depends_on` and `base_from`. Merely setting `max_parallel: 1` does not make independent branches a valid stack. Reviewers use `base_from` to inspect the implementation commit on a fresh machine. `parent_depth` must reflect the actual nesting depth, not always zero.

Optional adapter model settings live at `.agents/pstack.models.json`, or `pstack.models.json` beside `pstack/` on a volume. These are not native Capy configuration files. See [setup](adapter/SETUP.md) for the schema and precedence.

```bash
python3 .agents/pstack/tasks.py prepare plan.json --models .agents/pstack.models.json
```

Collect native results in a JSON array. Each record has `id`, `native_task_id`, `machine_id`, `status`, `base_sha`, `head_sha`, `branch` for writers, `changed_paths`, and `evidence`. Each evidence item has an exact `criterion` from the work order, `result: "pass"`, and an actual artifact reference. Read-only tasks must not change commits or files. Stack bases must equal the reported predecessor head.

```bash
python3 .agents/pstack/tasks.py check-results plan.json --results results.json
```

Successful structural validation returns `safe_to_ship: false`. Inspect the real diffs and artifacts, confirm the current PR head and required checks, and obtain an independent whole-PR verdict before any authorized shipping. A schema cannot authenticate a task's claims.

## Maintenance and removal

Rerun the installer from this pinned port to update an intact managed installation. Identical installs leave files unchanged. Local edits or missing managed files stop an update; preserve and reconcile them first. Keep custom skills, project instructions, and the model profile outside the managed source tree.

```bash
python3 tools/pstack.py uninstall --target /path/to/your-project --dry-run
python3 tools/pstack.py uninstall --target /path/to/your-project
```

Add `--volume` when removing a volume installation. Only tracked, hash-matching files are removed. Unrelated files and directories remain.

The installer uses an exclusive lock, a complete collision preflight, staged file replacements, and rollback on Python exceptions. It is **not a filesystem transaction across power loss or SIGKILL** and is not a defense against a malicious process with the same filesystem permissions. After an interrupted run, inspect the lock and manifest, preserve changed files, and reconcile before retrying. Never delete a lock held by a live installer.

An upstream update is an explicit port change: review the diff, update the gitlink and `PIN` together, update version metadata when needed, and rerun the complete integration tests. The installer never silently downloads a newer source.

## Verification and limits

```bash
python3 -m unittest discover -s tests -v
python3 tools/tasks.py prepare examples/plan.json
```

Tests cover installation behavior, ownership conflicts, symlinks and traversal, safe uninstall, rollback, volume layout, model profiles, task graph/stack validation, evidence gates, and the real command-line interface. The integration test requires the initialized pinned submodule, installs every source file, checks byte equality and all generated entry links, and checks idempotence. CI initializes that source and builds both project and volume bundles.

**Local installer tests are not a live Capy smoke test.** No authenticated Capy workspace was available during this implementation. Native discovery, actual task starts and notifications, machine handoff, volume persistence, model selection, browser verification, and automation wakeups still need the [live smoke checklist](docs/live-smoke.md). No Capy API key is needed for normal skill use or these local tests.

Capy's public task API is read-only. This port deliberately does not invent task-creation endpoints or pretend to have runtime hooks. Its workflow guarantees are instructions plus validation, not a sandbox, distributed lock, exactly-once scheduler, or proof that every future agent follows them. Source dependencies outside pstack, including Cursor's control and cleanup skills, are not magically bundled: the adapter requires a real equivalent capability or a blocked gate.

## Attribution

Original pstack: **Lauren Tan and contributors**, MIT. The upstream submodule and generated `upstream/LICENSE` retain its license. The adapter and tools are MIT, Copyright 2026 ThewindMom; see [LICENSE](LICENSE). The source is pinned, not vendored from your private repositories. This is an independent adaptation, not an official Cursor or Capy integration.
