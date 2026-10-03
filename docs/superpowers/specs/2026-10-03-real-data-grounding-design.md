# CarbonOpt AI: real-data grounding for a 1–2 hour hackathon finish

## Outcome and scope

The user wants this existing product grounded in real data and an implementation plan that Codex or Claude Code can execute. They have **only 1–2 hours** for implementation. Add one compact dashboard section that combines a public logistics-company reference, a calculation using official conversion factors, and, if the two-hour budget permits, a live electricity-intensity example. Preserve the working simulator and optimizer.

The primary target customer is a UK logistics operator with warehouses and a fleet. Use **Wincanton as a public reference company**, not as an actual customer or a company whose strategy we have validated. Its annual disclosure matches the logistics context of the repository's modelling CSV. The interactive six-action optimizer continues to analyse `demo-company` with synthetic inputs.

Success means a judge can inspect the source behind a reported number, change a consumption-reduction assumption and see a reproducible result, and distinguish those results from the synthetic optimization demo.

## Options considered

| Option | Benefit | Cost within this deadline | Decision |
|---|---|---|---|
| Public reference + official-factor calculator + grid card | Traceable real inputs and a visible interactive result | Roughly 100 minutes plus buffer | Recommended |
| Convert annual disclosures into a new monthly forecast provider | One company throughout the dashboard | Requires assumed activity drivers, financial mappings, adapter work and forecast validation | Defer |
| Connect AWS/Azure/GCP through Cloud Carbon Footprint | Account-specific cloud estimates | Credentials, billing access, setup and incomplete company activity data | Defer |

## Verified project constraints

- `app.py` runs Streamlit; use its existing layout and Plotly dependency.
- `src/actions/engine.py`, `src/optimization/`, and `src/integration/services.py` already implement the main decision workflow.
- `src.forecasting.provider` is absent. The current hybrid preset uses a fixture forecast. Adding reference data does not make that forecast real.
- `data/synthetic_data.csv` describes logistics in EUR and uses EBITDA. The dashboard contract uses GBP and operating profit. Relabelling the columns would be incorrect.
- `data/benchmark.csv` contains synthetic technology peers. It is unsuitable for benchmarking Wincanton without further work.
- The action engine uses a demonstrative renewable-share accounting model. Do not replace its grid factor alone and claim location-based corporate accounting: its renewable action still changes electricity emissions using a different basis.

## Real company reference

Use the [Wincanton Annual Review 2024](https://win-12731-s3.s3.eu-west-2.amazonaws.com/assets/7317/2796/5575/Wincanton_Annual_Review_2024.pdf), fiscal year ending **31 March 2024**. Financial data appears on printed pages 1 and 5; energy/emissions on printed pages 24–25, PDF page index 13. This is an explicitly historical snapshot, not the latest company performance.

| Field | Reported value | Unit |
|---|---:|---|
| Revenue | 1,406.6 | £m |
| Transport energy, Scope 1 | 1,025,192 | MWh |
| Non-transport energy, Scope 1 | 38,100 | MWh |
| Electricity, transport | 662 | MWh |
| Electricity, non-transport | 77,485 | MWh |
| Transport emissions, Scope 1 | 234,907 | tCO2e |
| Non-transport emissions, Scope 1 | 7,948 | tCO2e |
| Electricity emissions, transport | 149 | tCO2e |
| Electricity emissions, non-transport | 17,433 | tCO2e |
| Total Scope 1 and 2 | 260,437 | tCO2e |
| Scope 3 | 67,039 | tCO2e |

Keep the report's categories and organizational boundary. Wincanton describes operations in the UK and Ireland; this snapshot does not establish an exclusively UK activity boundary. The calculator therefore applies a UK factor as a clearly labelled scenario proxy, not as a verified factor for every site. Scope 1 non-transport energy is **not** a verified natural-gas-only quantity. Do not convert aggregate transport MWh into invented diesel litres. Do not call EBITDA or profit before tax operating profit. Do not turn these annual totals into observed monthly records or synthetic training examples with a real-data label.

## How to use the three supplied sources

### GOV.UK: official emissions factors

The [2026 publication](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026) has a [July-revised flat workbook](https://assets.publishing.service.gov.uk/media/6a6c9748862aaf18d9c62ac9/ghg-conversion-factors-2026-flat-format-revised.xlsx). Its front page identifies version **1.2**, year **2026**. The following total-GHG factors were checked directly in `Factors by Category`:

| Optional factor key | Workbook factor ID | Row | Unit | Value |
|---|---|---:|---|---:|
| `uk_electricity` | `7_400_4000_5_1` | 3066 | kgCO2e/kWh | 0.13096 |
| `natural_gas_gross_cv` | `1_100_1004_6_1` | 83 | kgCO2e/kWh, Gross CV | 0.18231 |
| `diesel_average_biofuel` | `1_101_1011_8_1` | 187 | kgCO2e/litre | 2.58354 |

Only electricity is required for this sprint. Extract a tiny JSON snapshot once; avoid adding runtime spreadsheet parsing. Keep factor ID, row, units, year, version, source URL and retrieval date. Blank values are unavailable, not zero. Gas and diesel are future extensions and must use actual matching activity units. Combustion and well-to-tank factors belong to different scopes.

Default the calculator to the reported **77,485,000 kWh** of non-transport electricity. Apply the 2026 factor as a **current-factor sensitivity scenario using historical activity**. This is neither a reconstruction of the company's FY2024 Scope 2 disclosure nor a forecast of its 2026 consumption. Annual reporting should use period-appropriate factors; this sprint deliberately compares hypothetical scenarios under one fixed 2026 factor.

`scenario_tco2e = electricity_kwh × (1 − reduction_ratio) × 0.13096 / 1000`

At a 10% reduction, the calculated saving is **1,014.74356 tCO2e**, relative to a modeled baseline of **10,147.4356 tCO2e**. If a user enters an electricity tariff, show `saved_kwh × tariff` as **gross energy-cost savings before implementation costs**, not profit. Tariff and achievable reduction are assumptions; default tariff to £0.25/kWh and label it illustrative. No assertion that Wincanton can achieve the selected reduction.

### Carbon Intensity: operational electricity signal

The supplied GitHub organization links to the [official GB API documentation](https://carbon-intensity.github.io/api-definitions/). Use HTTPS requests to the API, rather than cloning repositories:

- `GET https://api.carbonintensity.org.uk/intensity` for a current reading, if desired.
- `GET https://api.carbonintensity.org.uk/intensity/{from}/fw48h` for the required chart and example.

The API needs no authentication. Its half-hour values concern electricity-generation **CO2**, in gCO2/kWh, and are not interchangeable with the GOV.UK annual CO2e reporting factor. Keep this panel separate from corporate annual totals and the optimizer. Attribute NESO and the API's CC BY 4.0 license.

For a one-hour, constant-power task consuming a user-assumed **100 kWh**, compare the earliest complete future two-slot window with the lowest-intensity contiguous two-slot window. Each slot uses 50 kWh. Display forecast kgCO2 and the difference; this is a GB-average scheduling illustration, not a depot-specific claim or guaranteed marginal avoided emissions. No annualization of its savings.

Use a five-second timeout, Streamlit caching for 1,800 seconds, and an explicit refresh control. The app and offline tests must not require network access at startup. Bundle a genuinely fetched response with URL and retrieval timestamp. An old snapshot is labelled **recorded example**; its historical best window is not offered as an upcoming recommendation. Missing `actual` values remain missing; scheduling uses `forecast`.

### Cloud Carbon Footprint: methodology and later integration

[CCF](https://github.com/cloud-carbon-footprint/cloud-carbon-footprint) estimates energy and emissions from cloud usage. It is an estimation tool, not a source of Wincanton's cloud billing records. Its [methodology](https://www.cloudcarbonfootprint.org/docs/methodology/) covers energy estimation, PUE and region-specific emissions factors.

For this sprint, link it in the sources section and state that cloud impact remains illustrative in the existing simulator. Do not install CCF or invent cloud measurements. Later, import account-specific CCF output containing kWh and tCO2e, together with provider, region and period. Preserve its accounting boundary; do not apply PUE twice or blindly overwrite its cloud-region factors with GB grid readings. CCF code reuse requires its Apache-2.0 attribution and notice handling.

## Global constraints

- Keep the existing Python/Streamlit stack; add no runtime dependencies.
- Keep the existing forecast, simulator, optimizer, risk and benchmark contracts unchanged.
- Keep reference data, calculator results and grid scheduling separate from the optimizer's synthetic inputs.
- Label each number as reported historical, official factor, forecast, recorded example, or assumption.
- Network failure must leave the existing dashboard usable and visibly label recorded data.
- Use kgCO2 for the grid example and tCO2e for the official-factor calculator; never combine them into a corporate total.
- Leave all existing fixture and action-assumption files unchanged.
- Stop implementation after 120 minutes; cut optional work before risking the working demo.

## Acceptance and presentation

The new section must load offline, show the exact annual reference and factor provenance, and reproduce the 10% saving above. At the two-hour scope it also shows a grid chart and valid scheduling example. Existing hybrid startup, optimization and infeasible-state tests remain passing. The existing assistant continues to explain its existing tools; it must not claim that the optimizer has gained Wincanton data.

Suggested demo statement: “We use public logistics-company activity and official conversion factors for this traceable scenario, and a real GB electricity forecast for this scheduling example. The six-action optimization remains an illustrative demo until a customer provides monthly activity, costs and financial data.”
