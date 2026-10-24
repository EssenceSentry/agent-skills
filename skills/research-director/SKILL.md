---
name: research-director
description: Direct research and data-science campaigns so effort goes to work that can change a decision. Use before running any nontrivial experiment, simulation, benchmark or analysis in a campaign, when planning a long autonomous research session, and after each result to choose the next step. Every experiment goes through `ax exp propose`, whose gate rejects work that names no decision, outcome-to-action mapping, cheaper alternative, stop rule or cost.
---

# Research director

The goal is better decisions and defensible findings per hour spent, not
more or bigger experiments. Not running an experiment is a legitimate,
often correct, choice.

## Before each experiment

1. Read the campaign's state: `ax exp list <campaign>` (budget, open
   proposals ranked by value per hour, stall warnings). Search earlier work
   with the session-recall skill before proposing something that may have
   been done.
2. Work out, in this order:
   - which decision or claim this could change;
   - the plausible outcomes, and what each would make you do differently;
   - whether cheaper adequate evidence exists: existing results, the data
     itself, an analytical bound, a counterexample, or a ten-replicate pilot;
   - what could make the inference invalid (identifiability, sampling,
     measurement);
   - the cost in hours and allowance, and what it displaces;
   - the result, failure or cost at which you stop.
3. Record it through the gate. If it fails, the missing pieces are the
   thinking still to do:

   ```bash
   ax exp propose <campaign> \
     --question "…" --decision "…" \
     --outcome "result A → action" --outcome "result B → other action" \
     --cheaper "…" --stop "…" --hours 2 --value 4 --p-change 0.5
   ```

   `value` (1-5) is how much the decision matters; `p-change` (0-1) is the
   chance the result changes it. Be honest: a simulation whose every outcome
   leads to the same action has `p-change` near 0.
4. Run the highest-scoring proposal unless a cheaper one answers the same
   question: `ax exp start <campaign> <id>`.

## After each result

- `ax exp finish <campaign> <id> --result "…" --hours 1.5 --decision-changed`
  (or `--no-decision-changed`), with `--insight "…"` for anything lasting.
- Re-rank: adjust `value` and `p_change` in the open experiments' notes when
  the evidence moves them, and propose newly sensible work.
- Rewrite "Current answer" in the campaign's Campaign.md in plain language.
- When `ax exp list` reports a stall, three results in a row that changed
  no decision, stop and reconsider the direction before spending more. Ask
  the user if the direction itself is in question.
- Record abandoned directions with `ax exp abandon … --dead-end` so they
  are not tried again.

## Guardrails

- Prefer analytical checks, data inspection and small falsification tests
  before expensive simulations. More Monte Carlo replicates reduce numerical
  noise, not model misspecification.
- Before long runs, check allowance with
  `ax usage guard --provider claude --window weekly` and stay within the
  campaign's `budget_hours`.
- A proposal passing the gate is not permission to exceed the campaign
  budget or the user's delegation rules. Escalate only when a constraint
  needs changing or a consequential decision needs the user.
