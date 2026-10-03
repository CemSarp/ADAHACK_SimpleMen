"""Independent audit of carbonopt-ai-docs/examples (stdlib only).

Re-derives fixture numbers from ACTION_MODEL.md hand equations and
RISK_AND_BENCHMARK_SPEC.md percentile rules. Audit evidence for readiness.md.
ponytail: AUDIT-ONLY oracle. Never import it from src/ or bind it as a
SimulationFn; WS2's simulate_strategy is the only production engine.

Run from repo root: python carbonopt-ai-docs/docs/handoffs/ws3/audit_examples.py
"""
import calendar, datetime as dt, hashlib, itertools, json, math, pathlib, statistics, sys

EX = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "carbonopt-ai-docs/examples")
load = lambda n: json.loads((EX / n).read_text())
ACTIONS = ["renewable_energy", "ev_adoption", "building_efficiency",
           "travel_reduction", "cloud_efficiency", "supplier_transition"]
fails = []

def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)

close = lambda a, b, atol=1e-6, rtol=1e-8: abs(a - b) <= atol + rtol * abs(b)
money = lambda a, b: abs(a - b) <= 0.01

# 1. every example parses, no NaN/Infinity tokens on the wire
for p in sorted(EX.glob("*.json")):
    def bad_const(c):
        raise ValueError(c)
    try:
        json.loads(p.read_text(), parse_constant=bad_const)
        check(f"parse+finite {p.name}", True)
    except ValueError as e:
        check(f"parse+finite {p.name}", False, str(e))

# 2. baseline
b = load("baseline_12m.json")
m = b["monthly"]
months = [r["timestamp"] for r in m]
he = dt.date.fromisoformat(b["history_end"])
exp = []
y, mo = he.year, he.month
for _ in range(b["horizon_months"]):
    mo += 1
    if mo == 13:
        y, mo = y + 1, 1
    exp.append(f"{y:04d}-{mo:02d}-01")
check("baseline 12 contiguous months after history_end", months == exp, f"{months[0]}..{months[-1]}")
check("baseline one company", {r["company_id"] for r in m} == {b["company_id"]})
for col, key in [("revenue_gbp", "revenue_gbp"), ("operating_profit_gbp", "operating_profit_gbp"),
                 ("total_co2e_tco2e", "total_co2e_tco2e")]:
    s = sum(r[col] for r in m)
    check(f"baseline sum {col}", close(s, b["totals"][key]), f"{s} vs {b['totals'][key]}")
check("baseline row scope identity",
      all(close(r["scope1_tco2e"] + r["scope2_tco2e"] + r["scope3_tco2e"], r["total_co2e_tco2e"]) for r in m))
check("baseline labelled synthetic + mock", b["data_kind"] == "synthetic" and b["provenance"]["is_mock"] is True)

# 3. independent hand-equation simulator (ACTION_MODEL.md section 3/4)
A = load("action_assumptions.json")
check("assumption scope1 partition sums to 1", close(A["gas_share"] + A["ice_fleet_share"], 1))
check("assumption scope3 partition sums to 1",
      close(A["travel_share"] + A["cloud_share"] + A["supplier_share"] + A["other_share"], 1))
check("adoption factors default 1.0",
      all(A[k] == 1 for k in ["renewable_effectiveness", "ev_effectiveness", "travel_effectiveness"]))

def hand_sim(cfg, a, cost_mult=None):
    cost_mult = cost_mult or {k: (1.0, 1.0) for k in ACTIONS}
    capex = sum(a["costs"][k]["capex_at_full_gbp"] * cost_mult[k][0] * cfg[k] for k in ACTIONS)
    fixed = sum(a["costs"][k]["monthly_opex_at_full_gbp"] * cost_mult[k][1] * cfg[k] for k in ACTIONS)
    dep_m = sum(a["costs"][k]["capex_at_full_gbp"] * cost_mult[k][0] * cfg[k]
                / a["costs"][k]["asset_life_months"] for k in ACTIONS)
    rows = []
    for i, r in enumerate(m):
        E, G, K, rr, v = r["electricity_kwh"], r["gas_kwh"], r["fleet_km"], r["renewable_energy_share"], r["ev_share"]
        s1, s2, s3 = r["scope1_tco2e"], r["scope2_tco2e"], r["scope3_tco2e"]
        bb = a["building_max_reduction"] * cfg["building_efficiency"]
        xr, xe = cfg["renewable_energy"] * a["renewable_effectiveness"], cfg["ev_adoption"] * a["ev_effectiveness"]
        r_new = rr + (1 - rr) * xr
        ev_km = K * (1 - v) * xe
        e_saved, g_saved = E * a["building_electricity_share"] * bb, G * a["building_gas_share"] * bb
        ev_kwh = ev_km * a["ev_kwh_per_km"]
        E_new = E - e_saved + ev_kwh
        sc1 = s1 * a["gas_share"] * (1 - a["building_gas_share"] * bb) + s1 * a["ice_fleet_share"] * (1 - xe)
        ex2 = s2 * (1 - e_saved / E) * (1 - r_new) / (1 - rr) if (rr < 1 and E > 0) else 0.0
        sc2 = ex2 + ev_kwh * a["grid_tco2e_per_kwh"] * (1 - r_new)
        xt = cfg["travel_reduction"] * a["travel_effectiveness"]
        sc3 = s3 * (a["travel_share"] * (1 - xt)
                    + a["cloud_share"] * (1 - a["cloud_max_reduction"] * cfg["cloud_efficiency"])
                    + a["supplier_share"] * (1 - a["supplier_max_reduction"] * cfg["supplier_transition"])
                    + a["other_share"])
        opex = fixed + ev_kwh * a["electricity_gbp_per_kwh"] + E_new * (r_new - rr) * a["renewable_premium_gbp_per_kwh"]
        sav = (e_saved * a["electricity_gbp_per_kwh"] + g_saved * a["gas_gbp_per_kwh"]
               + ev_km * a["ice_fuel_gbp_per_km"]
               + r["business_travel_km"] * xt * a["travel_gbp_per_km"]
               + r["cloud_compute_hours"] * a["cloud_max_reduction"] * cfg["cloud_efficiency"] * a["cloud_gbp_per_hour"]
               + a["supplier_monthly_savings_at_full_gbp"] * cfg["supplier_transition"])
        cx = capex if i == 0 else 0.0
        rows.append(dict(s1=sc1, s2=sc2, s3=sc3, co2=sc1 + sc2 + sc3,
                         profit=r["operating_profit_gbp"] + sav - opex - dep_m,
                         capex=cx, opex=opex, sav=sav, dep=dep_m, cost=cx + opex))
    tot = {k: sum(x[k] for x in rows) for k in rows[0]}
    return rows, tot

def check_sim(fname, cfg_expect=None):
    s = load(fname)
    cfg = s["config"]
    check(f"{fname} baseline_id joins", s["baseline_id"] == b["baseline_id"])
    check(f"{fname} dates match baseline", [r["timestamp"] for r in s["monthly"]] == months)
    rows, tot = hand_sim(cfg, A)
    mon = s["monthly"]
    check(f"{fname} monthly scope identity",
          all(close(r["scope1_tco2e"] + r["scope2_tco2e"] + r["scope3_tco2e"], r["total_co2e_tco2e"]) for r in mon))
    check(f"{fname} monthly budget_cost=capex+opex",
          all(money(r["budget_cost_gbp"], r["capex_gbp"] + r["incremental_opex_gbp"]) for r in mon))
    check(f"{fname} monthly net_cash=savings-opex-capex",
          all(money(r["net_cash_impact_gbp"], r["operating_savings_gbp"] - r["incremental_opex_gbp"] - r["capex_gbp"]) for r in mon))
    check(f"{fname} capex only month 1", all(r["capex_gbp"] == 0 for r in mon[1:]))
    check(f"{fname} profit = base + savings - opex - depreciation (capex not subtracted)",
          all(money(r["operating_profit_gbp"], br["operating_profit_gbp"] + r["operating_savings_gbp"]
                    - r["incremental_opex_gbp"] - r["depreciation_gbp"]) for r, br in zip(mon, m)))
    check(f"{fname} revenue unchanged", all(r["revenue_gbp"] == br["revenue_gbp"] for r, br in zip(mon, m)))
    check(f"{fname} hand-equation monthly scopes",
          all(close(r["scope1_tco2e"], h["s1"]) and close(r["scope2_tco2e"], h["s2"]) and close(r["scope3_tco2e"], h["s3"])
              for r, h in zip(mon, rows)))
    mt = s["metrics"]
    sums = {k: sum(r[k] for r in mon) for k in mon[0] if k != "timestamp"}
    pairs = [("total_co2e_tco2e", "total_co2e_tco2e", "co2", close),
             ("total_profit_gbp", "operating_profit_gbp", "profit", money),
             ("total_capex_gbp", "capex_gbp", "capex", money),
             ("total_incremental_opex_gbp", "incremental_opex_gbp", "opex", money),
             ("total_operating_savings_gbp", "operating_savings_gbp", "sav", money),
             ("total_cost_gbp", "budget_cost_gbp", "cost", money),
             ("net_cash_impact_gbp", "net_cash_impact_gbp", None, money)]
    for mk, col, hk, cmp in pairs:
        ok = cmp(mt[mk], sums[col]) and (hk is None or cmp(mt[mk], tot[hk]))
        check(f"{fname} metric {mk}", ok, f"fixture={mt[mk]} monthly_sum={sums[col]} hand={tot.get(hk)}")
    red = mt["baseline_total_co2e_tco2e"] - mt["total_co2e_tco2e"]
    check(f"{fname} reduction + ratio",
          close(mt["co2_reduction_tco2e"], red) and close(mt["co2_reduction_ratio"], red / mt["baseline_total_co2e_tco2e"]))
    pc = mt["total_profit_gbp"] - mt["baseline_total_profit_gbp"]
    check(f"{fname} profit change + ratio",
          money(mt["profit_change_gbp"], pc) and close(mt["profit_change_ratio"], pc / abs(mt["baseline_total_profit_gbp"])))
    ident = {"assumptions_id": A["assumptions_id"], "assumptions_version": A["version"],
             "baseline_id": s["baseline_id"], "config": {k: float(cfg[k]) for k in ACTIONS}}
    canon = json.dumps(ident, sort_keys=True, separators=(",", ":"))
    sid = "strategy-" + hashlib.sha256(canon.encode()).hexdigest()[:16]
    check(f"{fname} canonical strategy_id", sid == s["strategy_id"], f"{sid} payload={canon}")
    return s, tot

noop, _ = check_sim("simulation_noop.json")
check("no-op config all zero", all(noop["config"][k] == 0 for k in ACTIONS))
check("no-op monthly == baseline rows",
      all(r[k] == br[k] for r, br in zip(noop["monthly"], m)
          for k in ["operating_profit_gbp", "scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "total_co2e_tco2e"]))
check("no-op costs exactly zero", all(r[k] == 0 for r in noop["monthly"]
      for k in ["capex_gbp", "incremental_opex_gbp", "operating_savings_gbp", "depreciation_gbp", "budget_cost_gbp"]))

nz, nz_tot = check_sim("simulation_nonzero.json")
check("nonzero config == action_config.json", nz["config"] == load("action_config.json"))
golden = dict(co2=843.744, profit=1210940.7847619047, capex=164000.0, cost=186581.12)
for k, v in golden.items():
    check(f"nonzero golden {k} (hand equations)", close(nz_tot[k], v, atol=1e-6) if k == "co2" else money(nz_tot[k], v),
          f"hand={nz_tot[k]!r} golden={v}")
r0 = nz["monthly"][0]
check("nonzero monthly scopes 16.08/8.982/45.25",
      close(r0["scope1_tco2e"], 16.08) and close(r0["scope2_tco2e"], 8.982) and close(r0["scope3_tco2e"], 45.25))

# renewable final share example from DATA_SCHEMAS (0.2 + 0.8*0.7)
check("renewable final share 0.76", close(0.2 + (1 - 0.2) * 0.7, 0.76))

# 4. optimization fixtures join to simulator identities
for f in ["optimization_ok.json", "optimization_infeasible.json"]:
    o = load(f)
    ids = set(o["strategies"])
    cand_ids = {c["strategy_id"] for c in o["candidates"]}
    par_ids = {c["strategy_id"] for c in o["pareto"]}
    check(f"{f} candidate/pareto ids join strategies", cand_ids <= ids and par_ids <= ids,
          f"status={o['status']} cands={len(cand_ids)} pareto={len(par_ids)}")
    check(f"{f} pareto rows feasible rank 0", all(c["feasible"] and c["pareto_rank"] == 0 for c in o["pareto"]))
    check(f"{f} status/pareto consistency",
          (o["status"] == "ok" and len(o["pareto"]) >= 1) or (o["status"] == "infeasible" and len(o["pareto"]) == 0))
    for sid, sr in o["strategies"].items():
        _, t = hand_sim(sr["config"], A)
        check(f"{f} {sid} hand-sim totals", close(sr["metrics"]["total_co2e_tco2e"], t["co2"])
              and money(sr["metrics"]["total_profit_gbp"], t["profit"]) and money(sr["metrics"]["total_cost_gbp"], t["cost"]),
              f"co2={t['co2']:.6f} profit={t['profit']:.6f} cost={t['cost']:.6f}")

# 5. risk_summary: shape + consistency, and reachability under the documented initial ranges
rs = load("risk_summary.json")
SUMMARY = ["co2_mean_tco2e", "co2_p05_tco2e", "co2_p95_tco2e", "profit_mean_gbp", "profit_p05_gbp",
           "profit_p95_gbp", "cost_mean_gbp", "cost_p95_gbp", "target_probability", "profit_floor_probability",
           "budget_probability", "joint_feasibility_probability", "target_probability_mc_standard_error"]
check("risk_summary has exactly 13 summary fields", list(rs["summary"]) == SUMMARY)
check("risk_summary strategy_id is nonzero deterministic id", rs["strategy_id"] == nz["strategy_id"])
check("risk_summary labelled mock fixture", rs["provenance"]["is_mock"] is True and rs["provenance"]["provider"] == "fixture")
S, n = rs["summary"], rs["n_simulations"]
p = S["target_probability"]
check("risk_summary MCSE = sqrt(p(1-p)/n)", close(S["target_probability_mc_standard_error"], math.sqrt(p * (1 - p) / n)))
check("risk_summary joint <= min(marginals)",
      S["joint_feasibility_probability"] <= min(S["target_probability"], S["profit_floor_probability"], S["budget_probability"]))
# Effectiveness and cost multipliers are independent boxes; totals are multilinear in them, so extremes sit at vertices.
eff_lo, cost_b = 0.85, (0.9, 1.1)
ext = {"co2": [math.inf, -math.inf], "profit": [math.inf, -math.inf], "cost": [math.inf, -math.inf]}
cfg = nz["config"]
for effs in itertools.product([eff_lo, 1.0], repeat=6):
    e = dict(zip(ACTIONS, effs))
    a2 = dict(A)
    a2["renewable_effectiveness"], a2["ev_effectiveness"], a2["travel_effectiveness"] = \
        e["renewable_energy"], e["ev_adoption"], e["travel_reduction"]
    a2["building_max_reduction"] = A["building_max_reduction"] * e["building_efficiency"]
    a2["cloud_max_reduction"] = A["cloud_max_reduction"] * e["cloud_efficiency"]
    a2["supplier_max_reduction"] = A["supplier_max_reduction"] * e["supplier_transition"]
    a2["supplier_monthly_savings_at_full_gbp"] = A["supplier_monthly_savings_at_full_gbp"] * e["supplier_transition"]
    for cm in cost_b:
        _, t = hand_sim(cfg, a2, {k: (cm, cm) for k in ACTIONS})
        for k in ext:
            ext[k][0], ext[k][1] = min(ext[k][0], t[k]), max(ext[k][1], t[k])
print("reachable ranges under documented initial ranges + proposed A03 cost scope:",
      {k: (round(v[0], 3), round(v[1], 3)) for k, v in ext.items()})
for k, fields in [("co2", ["co2_mean_tco2e", "co2_p05_tco2e", "co2_p95_tco2e"]),
                  ("profit", ["profit_mean_gbp", "profit_p05_gbp", "profit_p95_gbp"]),
                  ("cost", ["cost_mean_gbp", "cost_p95_gbp"])]:
    for f in fields:
        inside = ext[k][0] - 1e-9 <= S[f] <= ext[k][1] + 1e-9
        print(f"INFO risk_summary {f}={S[f]} {'within' if inside else 'OUTSIDE'} reachable [{ext[k][0]:.3f}, {ext[k][1]:.3f}]")
con = load("constraints.json")
print("INFO deterministic nonzero vs constraints.json:",
      f"cost {golden['cost']} <= {con['budget_gbp']}", golden["cost"] <= con["budget_gbp"],
      f"| profit {golden['profit']} >= {con['min_total_profit_gbp']}", golden["profit"] >= con["min_total_profit_gbp"],
      f"| reduction {(1200-golden['co2'])/1200} >= {con['min_co2_reduction_ratio']}", (1200 - golden["co2"]) / 1200 >= con["min_co2_reduction_ratio"])
print(f"INFO worst-case reduction ratio {(1200-ext['co2'][1])/1200:.6f}; best-case {(1200-ext['co2'][0])/1200:.6f}")

# 6. benchmark peers + result
pk = load("benchmark_peers.json")
peers = pk["peers"]
ints = []
for r in peers:
    ps, pe = dt.date.fromisoformat(r["period_start"]), dt.date.fromisoformat(r["period_end"])
    y2, m2 = (ps.year + 1, ps.month)
    full = pe == dt.date(y2, m2, 1) - dt.timedelta(days=1) if ps.day == 1 else False
    i = r["total_co2e_tco2e"] / (r["revenue_gbp"] / 1_000_000)
    ints.append(i)
    check(f"peer {r['peer_id']} full 12 months / intensity / compat",
          full and close(i, r["intensity_tco2e_per_million_gbp"]) and r["revenue_gbp"] > 0 and r["total_co2e_tco2e"] >= 0
          and r["scope_coverage"] == "scope1_scope2_scope3" and r["scope2_method"] == b["scope2_method"]
          and r["is_synthetic"] is True and r["source_id"] == pk["metadata"]["source_id"],
          f"{r['period_start']}..{r['period_end']} intensity={i}")
check("peer ids unique", len({r["peer_id"] for r in peers}) == len(peers))
check("peer single industry", len({r["industry"] for r in peers}) == 1, str({r["industry"] for r in peers}))
check("peer intensities as documented", sorted(ints) == [40, 60, 80, 90, 100, 110, 120, 140, 160, 200], str(sorted(ints)))
c = b["totals"]["total_co2e_tco2e"] / (b["totals"]["revenue_gbp"] / 1_000_000)
tol = 1e-8
E_ = sum(abs(x - c) <= tol for x in ints)
L_ = sum(x < c - tol for x in ints)
pct = 100 * (L_ + 0.5 * E_) / len(ints)
br = load("benchmark_result.json")
check("company intensity 100", close(c, 100) and close(br["company_intensity_tco2e_per_million_gbp"], c))
check("median 105", statistics.median(ints) == 105 == br["industry_median"])
check("percentile 45 / better 55 / N 10", (L_, E_, len(ints)) == (4, 1, 10) and pct == 45 == br["percentile"]
      and 100 - pct == 55 == br["better_than_pct"] and br["peer_count"] == 10)
check("benchmark result status ok + synthetic labels", br["status"] == "ok" and br["is_synthetic"] is True
      and br["provenance"]["is_mock"] is True and br["comparison_basis"] == "forecast_vs_historical_peers")
check("benchmark result period = forecast period", br["period_start"] == months[0] and
      br["period_end"] == f"{months[-1][:8]}{calendar.monthrange(int(months[-1][:4]), int(months[-1][5:7]))[1]}")
peer_end = max(r["period_end"] for r in peers)
gap = (int(br["period_end"][:4]) * 12 + int(br["period_end"][5:7])) - (int(peer_end[:4]) * 12 + int(peer_end[5:7]))
check("peer period-end gap <= 24 months", 0 <= gap <= 24, f"gap={gap}")

# 7. synthetic future dates relative to retrieval / audit date
today = dt.date(2026, 10, 3)
print(f"INFO audit date {today}; baseline history_end {b['history_end']} (> today: {he > today}); "
      f"forecast {months[0]}..{months[-1]}; peer periods end {peer_end} (> retrieved_at {pk['metadata']['retrieved_at']}: "
      f"{dt.date.fromisoformat(peer_end) > dt.date.fromisoformat(pk['metadata']['retrieved_at'][:10])})")

print(f"\n{len(fails)} FAIL(S)" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
