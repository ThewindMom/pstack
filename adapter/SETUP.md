# Set up pstack in Capy

This replaces the Cursor setup skill. Do not write `~/.cursor/rules/pstack-models.mdc`.

1. Find the installed pstack directory from the skill entry. Check `provenance.json`.
   Read the existing `pstack.models.json` beside that directory when present. Preserve
   unrelated instructions and settings. No configuration is required for parent-model
   inheritance.
2. Observe the models available to this account through the actual Capy session. Never
   infer entitlement from a public model list or translate a Cursor model slug by guess.
   If models cannot be enumerated, keep `inherit-parent` or ask for the user's available
   choices. A saved model list is not proof of current entitlement.
3. Ask for desired cost/concurrency only when the user requests model tuning or when
   the planned panel needs a genuine choice. Show the exact role map before saving a
   changed profile. Do not imply arbitrary reasoning levels exist on every model.
4. Write the adapter profile below to `.agents/pstack.models.json` for project installs,
   or `pstack.models.json` at the installed volume root. Replace only that profile, not
   AGENTS.md. The adapter reads it; Capy does not load this file as native configuration.
5. Recheck choices when creating native tasks. Omit the native model argument for
   `inherit-parent`. Use the account's actual selection for other choices.

```json
{
  "confirmed_models": [],
  "max_parallel": 3,
  "roles": {
    "implementation": "inherit-parent",
    "research": "inherit-parent",
    "design": "inherit-parent",
    "review": "inherit-parent",
    "comment-review": "inherit-parent"
  }
}
```

To generate work orders with this profile, pass it explicitly:

```bash
python3 .agents/pstack/tasks.py prepare plan.json --models .agents/pstack.models.json
```

Per-task model choices override profile roles and must still occur in the observed
`confirmed_models` list. Panel seats can specify separate models. The number of seats
and whether they are genuinely different must remain visible to the user.

The installer does not overwrite this profile during upgrades. In a multi-repository
Capy project, place shared skills in one designated repository or a volume. Capy's
project repository order decides which duplicate skill name wins.
