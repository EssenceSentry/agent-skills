# Model fit and delegation examples

Research checked 2026-09-27. Routing combines the user's preferences and primary evidence; it is not an independent benchmark against Codex.

| Model / explicit ID | Evidence | Policy |
| --- | --- | --- |
| Opus 5.5 / `claude-opus-5-5` | Anthropic recommends it for most workloads. Its release describes performance comparable to Fable 5.1 on much of its evaluated coding and professional work. | Default for quality-sensitive delegation. Medium effort for routine work; high for subtle implementation/review; xhigh/max when extra reasoning has a purpose. |
| Fable 5.1 / `claude-fable-5-1` | The model overview positions it for demanding reasoning and long-horizon tasks, including when Opus at higher effort falls short. | Preferred for demanding independent reviews of parent or worker output, mathematical assumptions, architecture, and subtle correctness. Use directly when warranted; no Opus-first requirement. Don't use its separate allowance for routine extraction. |
| Sonnet 5 / `claude-sonnet-5` | Its release reports stronger agentic coding, tools and reasoning than Sonnet 4.6, approaching older Opus 4.8 on some evaluations. That doesn't establish parity with Opus 5.5. | Focused implementation/review batches. Start at medium effort, use high when warranted. |
| Haiku 4.5 / `claude-haiku-4-5-20251001` | Its release reports 73.3% SWE-bench Verified under its specified scaffold and settings. This supports coding ability, not universal reliability or direct comparison with newer benchmarks. | Short, clear tasks with cheap verification. Omit `--effort`; this model doesn't support it. |

Standard API input/output prices per million tokens at research time: Fable $10/$50, Opus $4/$20, Sonnet $2/$10, Haiku $1/$5. These describe API economics, not an exact subscription-quota conversion. Caching, effort, output length, retries and routing matter. Don't select a weaker model only to minimize estimated dollars while ample included usage expires.

The helper pins IDs. CLI aliases and provider routing may change the model actually used. Record `system/init.model`, assistant message models and final `modelUsage`; report mismatches. Account availability is established by the real CLI response.

## Primary sources

- [Model lineup, IDs, effort and pricing](https://platform.claude.com/docs/en/models/overview)
- [Opus 5.5 specifications](https://platform.claude.com/docs/en/models/opus-5-5/overview)
- [Opus capability and evaluation notes](https://www.anthropic.com/claude/opus)
- [Sonnet 5 release and methodology](https://www.anthropic.com/news/claude-sonnet-5)
- [Haiku 4.5 release and SWE-bench methodology](https://www.anthropic.com/news/claude-haiku-4-5)

These are vendor evaluations. Scaffold, effort and benchmark version affect results. Task-specific pilots and parent verification determine whether a delegation succeeds.

## Concrete examples

### Opus: reusable feature-atlas component

Delegate the coherent atlas interaction: feature semantics, typed data, selection identity, rendering, and accessibility. Supply its data producers and consuming views as context even when edits are confined to the component and stylesheet. Group closely related UI defects with the same worker so it can assess the whole interaction. Require representative empty and dense-data states and actual checks.

The parent chooses the mathematical encoding and public interface, inspects the rendered result, verifies selection links to the right records, and integrates it. A reversible visual change can still merit Opus's quality.

### Opus: independent workflow review

Assign a complete question such as whether training and evaluation avoid data leakage. Give one reviewer the dataset construction, splitting, feature fitting, training, evaluation, and relevant consumer usage across module or repository boundaries. Require reproducible failures, trigger conditions, and evidence locations. Keep related hypotheses and reproductions together; consolidate duplicate findings before assigning further verification. Use separate reviewers for other independent questions or consequential conclusions needing fresh scrutiny. Supply constraints without an expected answer; the parent confirms findings and chooses in-scope repairs.

### Fable: uncertainty calculation critique

Provide a fully specified stratified mini-audit estimator, sampling scheme, priors and simulation code in a fresh reviewer context, without the implementer's self-assessment. Ask for a case where the interval loses its claimed interpretation, or a precise explanation of assumptions preventing one. Use Fable directly when this depth of scrutiny is warranted, including for parent-authored work. Require concise findings with counterexamples and evidence locations. The parent reproduces consequential findings and owns the statistical interpretation and methodological changes.

### Sonnet: disjoint compatibility checks

Group adapters or views by the compatibility contract and shared context they require. One worker can check several related adapters end to end. Parallelize separate contracts or independently verifiable batches, with unique owned paths and explicit shared interfaces. Request missing cases and small fixes, supported by validation. Use a pilot when the migration pattern is uncertain. The parent checks integration; shared interfaces have one write owner.

### Haiku: structured inventory

Split 25–100 short items per batch, retaining stable IDs. For example, extract public function names, input/output contracts and source locations from supplied snippets. Require JSON fields `id`, `facts`, `source`, `uncertain`; prohibit invented facts and allow abstention. Mechanically check schema, ID coverage, duplicates and source references; review a sample and all abstentions. Escalate ambiguous items, or use parsing when sufficient.

### Haiku: local annotation batches

Potential use case: first-pass image or text annotation with an explicit rubric, such as weapon present, absent, or uncertain in a thumbnail. Haiku accepts [text and image inputs](https://platform.claude.com/docs/en/models/haiku-4-5/overview). Run batching and save results locally through Claude Code; [model inference remains remote](https://code.claude.com/docs/en/data-usage#local-claude-code-data-flow-and-dependencies).

Start with a small human-reviewed pilot. Return stable item IDs, proposed labels, brief evidence tied to its input source, and an abstention option. Validate ID coverage and label quality before scaling. Cache by input identity, model, and rubric version; keep proposals separate from human-confirmed labels. Escalate ambiguous cases to Opus or human review and check a random quality sample. The parent defines the rubric and evaluates quality without reading every annotation.

### Near-reset capacity

With substantial allowance expiring soon, advance useful independent contexts in parallel while preserving capacity to verify and synthesize them. For example, a workflow-correctness review and a rendered-UI audit may proceed independently if each has the evidence it needs. Scale from actual useful returns and remaining allowance. Do not split one investigation into many thin assignments, or manufacture rewrites and redundant opinions merely to spend quota.
