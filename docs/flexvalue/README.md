# FlexValue build pack

Prepared on 3 October 2026 for four people, eight hours, Django and Plotly.

**Product:** Help a small organisation running its own compute decide when to run batch jobs, and measure the value of relaxing each operational constraint. The distinctive result is a ranked list of deadlines, release times and concurrency limits whose relaxation improves the chosen financial/carbon objective.

**Recommendation:** Build one site, one reproducible data snapshot, a correct scheduler and the constraint-value table first. Add a carbon-price control and a schedule comparison. Regional comparison is a stretch feature. Annualisation is an explicitly conditional calculator, never an annual forecast.

## Read in this order

1. [Architecture and decision register](01-architecture.md): analysis of the idea, recommended decisions and their reasons, mathematics, data contracts, application boundaries and limits.
2. [Eight-hour implementation guide](02-build-guide.md): four owners, parallel work, exact integration order, task interfaces, verification gates and cuts if behind schedule.
3. [Iterative coding-agent prompts](03-agent-prompts.md): a shared context prompt, setup prompt, four ownership prompts, integration prompts and release review. Feed one iteration at a time.
4. [Edge cases and acceptance checks](04-edge-cases.md): behaviour for invalid inputs, missing data, DST, negative prices, infeasibility, solver timeouts and misleading claims.
5. [Research evidence](05-sources.md): verified sources, current product discovery, saved raw responses and limitations of the verification.

## What is already decided versus proposed

User decisions: FlexValue; four team members; roughly eight hours; Django and Plotly; iterative coding-agent prompts with explanations of why.

User suggestions evaluated here: real Octopus half-hourly prices and NESO carbon forecasts; privately operated compute; carbon-price trade-offs; individual constraint relaxations; regional comparison; annual scaling.

Recommended defaults, **not earlier user decisions**: Python 3.11 and Django 5.2 LTS; SciPy MILP; one job occupies one homogeneous worker; non-preemptive jobs; 24 elapsed hours; local-first demo; no product database; power represented by average wall draw plus explicit idle and facility overhead; domestic Agile as a labelled proxy until a business tariff is verified. These can be changed before implementation. The architecture file explains the consequences.

## What exists now

This pack contains plans and prompts, not an implemented application. Public provider responses have been saved in `research/` so implementation can begin with real reproducible data. They cover a historical replay window, not a proven prospective scheduling experiment.

The repository currently has a Python 3.11 Conda environment specification, NumPy/SciPy/Plotly and related packages. Django is not declared. `README.md` is in an unresolved Git conflict (`UU` when inspected). This planning task does not resolve that conflict, stage files, commit, or change the environment. The integration owner should review the Git state before starting product work; do not abort or overwrite an existing merge/rebase automatically.

## First 30 minutes

- All four people read the decision summary and approve or change defaults together.
- Pick owners A–D using the build guide.
- A and B agree on domain types; D publishes the skeleton and contract checkpoint; C starts against a labelled fixture.
- Verify the saved data aligns to 48 main slots and four padding slots.
- Each person gives their coding agent the shared context and their ownership prompt. No two agents own the same files.

## Pitch

“Businesses know their electricity bill. They rarely know what each deadline adds to it. FlexValue schedules the same compute workload and shows the value of one more hour of flexibility, in pounds and estimated carbon.”

A successful demo must also show one zero-value relaxation. The product is useful because it identifies which rules matter, not because every relaxed rule must produce savings.
