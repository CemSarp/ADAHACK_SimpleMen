# FlexValue source verification and saved evidence

Research performed on 3 October 2026. These sources establish API behaviour and implementation feasibility; they do not establish that the product is globally novel, that a particular business is eligible for a tariff, or that estimated savings will be realised.

## Official references

| Source | What it supports |
|---|---|
| [Octopus REST endpoint guide](https://docs.octopus.energy/rest/guides/endpoints/) | Public product discovery, tariff metadata, rate endpoints, pagination, UTC handling and rate fields. |
| [Live product catalogue](https://api.octopus.energy/v1/products/) | At inspection, domestic Agile import product `AGILE-24-10-01` was returned alongside a separate Outgoing export product. Discover again before a new live capture. |
| [Inspected Agile product](https://api.octopus.energy/v1/products/AGILE-24-10-01/) | `is_business=false`, `direction=IMPORT`, and available regional tariff links. This is a domestic proxy unless replaced by a verified business feed. |
| [Octopus business Agile monitoring guidance](https://octopus.energy/help-and-faqs/articles/how-monitor-shape-shifters-agile-prices-business/) | Business Shape Shifters Agile exists and has rate/API access. Its actual pricing endpoint was not independently validated in this planning task. |
| [NESO API definitions](https://carbon-intensity.github.io/api-definitions/) | Regional endpoints, UTC intervals, forecast field and region IDs. Carbon values concern electricity generation, not the whole business lifecycle. |
| [NESO overview](https://carbonintensity.org.uk/) | Purpose and scope of regional carbon-intensity forecasts. |
| [SciPy MILP reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html) | Integer constraints, time limits, result statuses and HiGHS backend. Runtime on this workload still requires implementation-time measurement. |
| [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/) | LTS release compatible with the repository's Python 3.11 choice. Select an up-to-date compatible patch during setup. |
| [Carbon Aware SDK overview](https://carbon-aware-sdk.greensoftware.foundation/docs/overview) | Carbon-aware time/location scheduling already exists. FlexValue's proposed distinction is its explicit operational-constraint valuation workflow. |

The attached G-Research challenge and CarbonOpt proposal were read in the preceding conversation. The challenge's assessment categories were teamwork, originality, sustainability theme, presentation and project quality. The proposal's ML/Monte Carlo/NSGA-II/SHAP stack was a suggested design, not a challenge requirement; this plan replaces it with direct scheduling optimisation.

## Saved raw evidence

The [research manifest](research/manifest.json) contains each full request URL, retrieval timestamp and SHA-256. Original HTTP bodies are saved without reshaping. Files include products, product details, example postcode-region lookups, London/South Scotland rates and regional carbon responses.

Data window requested: **1 October 2026 14:00 UTC to 2 October 2026 16:00 UTC**. Proposed main scheduling window: **1 October 15:00 UTC to 2 October 15:00 UTC**, which is 16:00 BST to 16:00 BST. One hour of padding exists on each side.

| Dataset | Raw price rows | Raw carbon rows | Aligned half-hours after clipping | Observed price range, p/kWh ex VAT | Observed carbon range, gCO2/kWh |
|---|---:|---:|---:|---:|---:|
| London | 52 | 53 | 52 | 21.36–50.06 | 98–275 |
| South Scotland | 52 | 53 | 52 | 22.60–53.13 | 0–9 |

Checks actually performed in this planning task: all saved JSON parsed; SHA-256 values match saved files; each region has exactly the expected 52 matching UTC half-hours after clipping; every matched interval is 30 minutes. The extra carbon record is a leading boundary interval. No schedule has been solved yet, so there are no verified savings or performance claims.

Example site mappings were independently checked through provider APIs: a London example postcode returned tariff group `_C`; an Edinburgh example returned `_N`; NESO's Edinburgh district returned region 2, South Scotland. NESO documents London as region 13. These mappings apply to those examples; resolve actual sites rather than assuming tariff letters and NESO IDs are interchangeable.

The low South Scotland intensity in this window is an observation, not a universal regional fact. It does not by itself establish the value of temporal flexibility. That depends on variation, feasible windows, tariffs and competition for capacity.

## Limitations of the evidence

- This is a historical replay retrieved after the proposed schedule window. No claim is made that the exact forecast values were available before those jobs would have run.
- Saved prices are real domestic tariff observations used for an illustrative business model. Business rates/contract eligibility remain unverified.
- Price fields are used as returned; no inferred VAT multiplier or retail-price reconstruction is needed.
- Job durations, power, installed capacity and facility overhead in the demo are illustrative estimates, not observations from a real lab.
- Neither an annual representative sample nor forecast-error calibration has been collected.
- No business data or account credentials were accessed, and no app implementation or deployment was performed.
