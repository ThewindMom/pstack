# Live Capy smoke test

Status: not executed in an authenticated Capy workspace during implementation.
Run on a disposable repository and, for the volume checks, a caller-selected test volume.
Record actual task/machine IDs and artifact references. Never use fabricated IDs from a fixture.

1. Install from the pinned submodule into the test project. Run `doctor`, commit the
   generated files with authorization, and start a new Capy thread on that revision.
   Confirm `poteto-mode`, `setup-pstack`, `how`, and a principle appear as discovered
   skills. Read their actual paths; confirm adapter-first and source-relative loading.
2. Ask for a small read-only investigation. Confirm the complete matching playbook
   and referenced principle are read, not the whole catalog or Cursor-local history.
3. Prepare two disjoint writer tasks and a dependent reviewer. Start them through
   the native tools, explicitly choosing fresh machines for writers. Confirm actual
   placement and base commits, and confirm each child has the adapter files.
4. Inspect live progress without restarting the owners. Verify that a final child
   report wakes its parent and that idle/stopped is not accepted as done.
5. Create an input that exists only on the parent machine. Confirm that it is absent
   from a fresh child until transferred using native `transfer_files`. Verify content
   after transfer; never push a private file solely to make the test pass.
6. Give a dependent writer overlapping paths. Confirm it is based on the predecessor's
   actual branch/head, not merely launched later from main. Run the result checker
   against actual commits and evidence, then perform independent whole-diff review.
7. Try an overlapping independent writer plan, missing evidence, failed/idle result,
   and an unavailable model. Each must block, without creating duplicate tasks or
   claiming model diversity. Recheck available models through the live session.
8. Install into the intended test volume, attach it, and repeat skill discovery on
   another machine. Confirm real file visibility and precedence. Test restart/wake
   behavior through Capy's normal lifecycle, not a destructive VM operation.
9. Only with explicit authorization, create one bounded native automation and verify
   its observed wakeup and idempotent domain action. Without authorization, mark this
   check not run; never substitute a detached cron or a promise to monitor.
10. Uninstall from the test target and confirm unrelated skills, AGENTS.md, and the
    user model profile remain. Record any unavailable platform capability as blocked.

Do not label the live port verified until the applicable checks pass on the actual
Capy version/account. Local unit tests and reported task summaries are not substitutes.
