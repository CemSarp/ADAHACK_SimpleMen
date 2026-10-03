"""Synthetic monthly data generator for a growing logistics / supply-chain company.

The generator simulates (by default) 25 years (2001-2025) of monthly operational, financial
and emissions data for a mid-sized logistics company. The design follows three
principles:

1. **Activity first, emissions derived.** Freight volume drives fleet, energy,
   cost and revenue; emissions are computed from activity data through emission
   factors. The clean dataset is therefore internally consistent and can serve
   as ground truth for what-if scenario modelling.
2. **Correlated latent drivers.** A shared demand index (trend x seasonality x
   macro shocks x AR(1) noise) propagates to most columns, producing realistic
   multicollinearity (e.g. volume <-> fleet <-> diesel <-> scope 1 <-> revenue).
3. **Column-specific measurement noise.** A separate measurement layer mimics
   how each quantity is actually recorded (metered, invoiced, estimated,
   published annually, counted, ...), so each column gets noise of a fitting
   type and size.

Example:
    >>> gen = SupplyChainDataGenerator(GeneratorConfig(seed=7))
    >>> noisy = gen.generate()
    >>> clean = gen.clean_data_
    >>> dirty, log = gen.inject_data_quality_issues(noisy)
    >>> fig = gen.plot_time_series()
    >>> fig = gen.plot_correlation_heatmap(transform="yoy_change")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import EngFormatter, PercentFormatter

# --------------------------------------------------------------------------- #
# Domain constants
# --------------------------------------------------------------------------- #

# Monthly freight seasonality (Jan..Dec): Q4 retail peak, summer & Feb lull.
DEMAND_SEASONALITY = np.array(
    [0.80, 0.78, 0.93, 0.99, 1.03, 1.00, 0.87, 0.82, 1.05, 1.14, 1.27, 1.22]
)

# Multiplicative macro shocks on freight demand, keyed by "YYYY-MM".
DEMAND_SHOCKS = {
    # 2008-09 global financial crisis.
    "2008-10": 0.97, "2008-11": 0.93, "2008-12": 0.90, "2009-01": 0.86,
    "2009-02": 0.85, "2009-03": 0.87, "2009-04": 0.88, "2009-05": 0.90,
    "2009-06": 0.92, "2009-07": 0.94, "2009-08": 0.95, "2009-09": 0.96,
    "2009-10": 0.97, "2009-11": 0.98, "2009-12": 0.99,
    # COVID-19 lockdowns and recovery.
    "2020-03": 0.93, "2020-04": 0.76, "2020-05": 0.80, "2020-06": 0.88,
    "2020-07": 0.94, "2020-08": 0.97,
    # E-commerce boom after lockdowns.
    "2020-11": 1.04, "2020-12": 1.05, "2021-01": 1.04, "2021-02": 1.04,
    "2021-03": 1.03, "2021-04": 1.03, "2021-05": 1.02, "2021-06": 1.02,
    # 2023 freight recession (de-stocking).
    "2023-02": 0.97, "2023-03": 0.96, "2023-04": 0.96, "2023-05": 0.96,
    "2023-06": 0.97, "2023-07": 0.97, "2023-08": 0.98,
}

# Yearly anchor values for market prices (interpolated to monthly).
DIESEL_PRICE_ANCHORS = {  # EUR / litre (ex-VAT, commercial)
    2001: 0.82, 2002: 0.80, 2003: 0.83, 2004: 0.92, 2005: 1.05, 2006: 1.12,
    2007: 1.13, 2008: 1.33, 2009: 1.05, 2010: 1.22,
    2011: 1.40, 2012: 1.48, 2013: 1.42, 2014: 1.36, 2015: 1.18, 2016: 1.08,
    2017: 1.20, 2018: 1.32, 2019: 1.30, 2020: 1.12, 2021: 1.40, 2022: 1.85,
    2023: 1.68, 2024: 1.62, 2025: 1.58,
}
ELECTRICITY_PRICE_ANCHORS = {  # EUR / kWh (industrial)
    2001: 0.065, 2002: 0.066, 2003: 0.070, 2004: 0.073, 2005: 0.078,
    2006: 0.087, 2007: 0.092, 2008: 0.098, 2009: 0.102, 2010: 0.105,
    2011: 0.110, 2012: 0.115, 2013: 0.118, 2014: 0.120, 2015: 0.116,
    2016: 0.112, 2017: 0.114, 2018: 0.120, 2019: 0.125, 2020: 0.118,
    2021: 0.150, 2022: 0.280, 2023: 0.230, 2024: 0.200, 2025: 0.195,
}
CARBON_PRICE_ANCHORS = {  # EUR / tCO2e (EU ETS-like, launched 2005)
    2001: 0.0, 2002: 0.0, 2003: 0.0, 2004: 0.0, 2005: 22.0, 2006: 17.0,
    2007: 0.7, 2008: 22.0, 2009: 13.0, 2010: 14.5,
    2011: 13.0, 2012: 7.5, 2013: 4.5, 2014: 6.0, 2015: 7.7, 2016: 5.3,
    2017: 5.8, 2018: 15.5, 2019: 24.8, 2020: 24.7, 2021: 53.5, 2022: 80.9,
    2023: 85.0, 2024: 65.0, 2025: 72.0,
}
GRID_EF_ANCHORS = {  # kgCO2e / kWh, location-based grid average
    2001: 0.50, 2005: 0.48, 2008: 0.46, 2011: 0.42, 2015: 0.36,
    2020: 0.28, 2025: 0.22,
}

# Emission factors.
EF_DIESEL_KG_PER_L = 2.68          # tank-to-wheel, scope 1
EF_DIESEL_WTT_KG_PER_L = 0.61      # well-to-tank, scope 3
EF_GAS_KG_PER_KWH = 0.183          # natural gas heating, scope 1
EF_ELEC_WTT_KG_PER_KWH = 0.045     # T&D losses + upstream, scope 3
EF_SUBCONTRACT_KG_PER_TKM = {      # scope 3, cat. 4 upstream transport
    "road": 0.105, "rail": 0.028, "sea": 0.014, "air": 0.600,
}
EF_SPEND_KG_PER_EUR = 0.20         # spend-based purchased goods & services

# Operational parameters.
PAYLOAD_T = 18.0                   # average truck payload at full load
KM_PER_TRUCK_MONTH = 9_000.0       # km a truck can drive per month
WAREHOUSE_AREA0_M2 = 60_000.0      # initial warehouse area (for base_tkm=25M)
EV_MAX_SHARE = 0.22                # long-run EV share reachable by horizon
EV_TRUCK_COST_EUR = 160_000.0      # purchase cost of an e-truck in 2018

# Commercial parameters (year-0 prices, inflated over time).
FREIGHT_RATE_EUR_PER_TKM = {"road": 0.130, "rail": 0.070, "sea": 0.035, "air": 1.250}
SUBCONTRACT_COST_EUR_PER_TKM = {"road": 0.095, "rail": 0.052, "sea": 0.025, "air": 0.920}
MODES = ("road", "rail", "sea", "air")

# Columns treated as optimisation targets (shown first in heatmaps).
TARGET_COLUMNS = ("ebitda_eur", "total_emissions_tco2e")

# Plot styling.
COLOR_REPORTED = "#2a78d6"
COLOR_CLEAN = "#eb6834"
COLOR_INK = "#0b0b0b"
COLOR_INK_MUTED = "#898781"
COLOR_GRID = "#e4e3df"
DIVERGING_CMAP = LinearSegmentedColormap.from_list(
    "blue_gray_red", ["#2a78d6", "#f0efec", "#e34948"])


@dataclass
class GeneratorConfig:
    """Configuration for :class:`SupplyChainDataGenerator`.

    Attributes:
        start_date: First month of the series, formatted ``YYYY-MM-01``.
        n_months: Number of monthly observations.
        seed: Random seed for reproducibility.
        base_tkm: Freight volume of the first month in tonne-km. Scales the
            whole company (fleet, warehouses, revenue, emissions).
        annual_growth: Long-run annual growth rate of freight demand.
        noise_level: Global multiplier for all measurement-noise magnitudes
            and probabilities. ``0`` disables the measurement layer, ``1`` is
            the default level of realism.
        seasonality_strength: Multiplier for every seasonal amplitude (demand,
            mode mix, efficiency, energy, pricing). ``0`` removes seasonality,
            ``1`` is the default, values above 1 exaggerate it.
    """

    start_date: str = "2001-01-01"
    n_months: int = 300
    seed: int = 42
    base_tkm: float = 25e6
    annual_growth: float = 0.07
    noise_level: float = 1.0
    seasonality_strength: float = 1.0


class SupplyChainDataGenerator:
    """Generates monthly synthetic data for a growing logistics company.

    The output covers operations (freight volume, transport mode mix, fleet,
    load factor, energy use), markets (diesel, electricity and carbon prices),
    finance (revenue, operating cost, EBITDA, green capex) and GHG emissions
    (scopes 1, 2 and 3).

    Attributes:
        config: The generator configuration.
        rng: NumPy random generator, re-seeded on every :meth:`generate` call.
        dates: Monthly timestamps (month start).
        clean_data_: Ground-truth dataset from the last :meth:`generate` call.
        noisy_data_: Dataset with measurement noise from the last call.
    """

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        """Initialises the generator and its time axis.

        Args:
            config: Generator configuration. Defaults to
                :class:`GeneratorConfig` with default values.
        """
        self.config = config or GeneratorConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.dates = pd.date_range(
            self.config.start_date, periods=self.config.n_months, freq="MS"
        )
        self.n = len(self.dates)
        self.month = self.dates.month.to_numpy()
        self.years = np.arange(self.n) / 12.0
        self.calendar_year = self.dates.year.to_numpy() + (self.month - 0.5) / 12.0
        # Seasonal shape helpers in [0, 1]: peak in January / July respectively.
        self.winter = 0.5 * (1 + np.cos(2 * np.pi * (self.month - 1) / 12))
        self.summer = 0.5 * (1 + np.cos(2 * np.pi * (self.month - 7) / 12))
        # Seasonal amplitude multiplier and seasonal month masks.
        self.season = self.config.seasonality_strength
        self.q4 = np.isin(self.month, [10, 11, 12])
        self.holiday = np.isin(self.month, [7, 8])
        self.clean_data_: pd.DataFrame | None = None
        self.noisy_data_: pd.DataFrame | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate(self) -> pd.DataFrame:
        """Simulates the true process and applies measurement noise.

        The random generator is re-seeded so that repeated calls return
        identical data for the same configuration.

        Returns:
            The noisy ("as reported") monthly dataset. The noise-free ground
            truth is stored in :attr:`clean_data_`.
        """
        self.rng = np.random.default_rng(self.config.seed)
        clean = self._simulate_true_process()
        noisy = self._apply_measurement_noise(clean)
        self.clean_data_, self.noisy_data_ = clean, noisy
        return noisy

    def inject_data_quality_issues(
        self,
        df: pd.DataFrame,
        missing_rate: float = 0.02,
        typo_rate: float = 0.004,
        n_duplicates: int = 2,
        seed_offset: int = 1,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Corrupts a dataset with typical data-quality problems.

        This is separate from measurement noise: it simulates errors in data
        handling rather than in measurement. It adds:

        * random missing cells (MCAR) across numeric columns,
        * a 3-month block gap in the financial columns (ERP migration),
        * decimal typos (x10 or /10) in random cells,
        * a unit error: electricity reported in MWh instead of kWh for 4 months,
        * duplicated rows.

        Args:
            df: Dataset to corrupt (typically the output of :meth:`generate`).
            missing_rate: Fraction of numeric cells set to NaN at random.
            typo_rate: Fraction of numeric cells hit by a decimal typo.
            n_duplicates: Number of rows to duplicate.
            seed_offset: Offset added to the config seed so that the corruption
                is reproducible but independent of the generation noise.

        Returns:
            A tuple ``(corrupted_df, issue_log)`` where ``issue_log`` lists
            every injected issue with its row date, column and type.
        """
        rng = np.random.default_rng(self.config.seed + seed_offset)
        out = df.copy().reset_index(drop=True)
        log: list[dict] = []
        numeric_cols = [c for c in out.columns if c != "date"]

        # Random missing cells.
        mask = rng.random((len(out), len(numeric_cols))) < missing_rate
        for i, j in zip(*np.nonzero(mask)):
            out.loc[i, numeric_cols[j]] = np.nan
            log.append({"date": out.loc[i, "date"], "column": numeric_cols[j],
                        "issue": "missing_random"})

        # Block gap in financials (ERP migration).
        financial_cols = ["revenue_eur", "operating_cost_eur", "ebitda_eur", "green_capex_eur"]
        start = int(rng.integers(12, len(out) - 3))
        out.loc[start:start + 2, financial_cols] = np.nan
        for i in range(start, start + 3):
            for col in financial_cols:
                log.append({"date": out.loc[i, "date"], "column": col,
                            "issue": "missing_block_erp_migration"})

        # Decimal typos.
        mask = rng.random((len(out), len(numeric_cols))) < typo_rate
        for i, j in zip(*np.nonzero(mask)):
            col = numeric_cols[j]
            factor = rng.choice([10.0, 0.1])
            if pd.notna(out.loc[i, col]):
                out.loc[i, col] = out.loc[i, col] * factor
                log.append({"date": out.loc[i, "date"], "column": col,
                            "issue": f"typo_x{factor:g}"})

        # Unit error: kWh -> MWh for four consecutive months.
        start = int(rng.integers(0, len(out) - 4))
        out.loc[start:start + 3, "electricity_consumption_kwh"] /= 1000.0
        for i in range(start, start + 4):
            log.append({"date": out.loc[i, "date"],
                        "column": "electricity_consumption_kwh",
                        "issue": "unit_error_mwh"})

        # Duplicated rows.
        dup_idx = rng.choice(len(out), size=n_duplicates, replace=False)
        for i in dup_idx:
            log.append({"date": out.loc[i, "date"], "column": "<row>",
                        "issue": "duplicate_row"})
        out = pd.concat([out, out.loc[dup_idx]]).sort_values("date", kind="stable")

        return out.reset_index(drop=True), pd.DataFrame(log)

    # ------------------------------------------------------------------ #
    # True (noise-free) process
    # ------------------------------------------------------------------ #

    def _simulate_true_process(self) -> pd.DataFrame:
        """Simulates the ground-truth data in dependency order.

        Returns:
            The clean monthly dataset with all output columns.
        """
        d: dict[str, np.ndarray] = {}
        d.update(self._simulate_demand())
        d.update(self._simulate_mode_mix(d["demand_idio"]))
        d.update(self._simulate_operations(d))
        d.update(self._simulate_fleet(d["vehicle_km"]))
        d.update(self._simulate_energy(d))
        d.update(self._simulate_market_prices())
        d.update(self._simulate_direct_emissions(d))
        d.update(self._simulate_green_capex(d["fleet_ev_count"]))
        d.update(self._simulate_financials(d))
        d.update(self._simulate_scope3(d))
        d["total_emissions_tco2e"] = (
            d["scope1_tco2e"] + d["scope2_tco2e"] + d["scope3_tco2e"]
        )
        return self._to_frame(d)

    def _simulate_demand(self) -> dict[str, np.ndarray]:
        """Builds the freight demand (tonne-km) from its latent components.

        Demand = base x exp(growth trend + business cycle + contract events
        + AR(1)) x seasonality x macro shocks.

        The seasonal amplitude varies from year to year (mild vs. strong
        peak seasons), and contract wins/losses cause persistent level shifts,
        so the series is random but keeps its trend and seasonal pattern.

        Returns:
            Dict with ``freight_volume_tkm`` and the idiosyncratic demand
            component ``demand_idio`` (reused to correlate other columns).
        """
        cfg = self.config
        trend = np.log1p(cfg.annual_growth) * self.years
        cycle = 0.04 * np.sin(2 * np.pi * self.years / 6.5 + 0.8)
        idio = self._ar1(phi=0.6, sigma=0.045)
        # Contract wins and losses: level shifts that fade over ~2-3 years.
        events = self.rng.random(self.n) < 0.05
        steps = events * self.rng.normal(0.0, 0.05, self.n)
        contracts = np.zeros(self.n)
        for t in range(1, self.n):
            contracts[t] = 0.97 * contracts[t - 1] + steps[t]
        # Seasonal deviations, scaled by strength and a per-year random factor.
        base_season = DEMAND_SEASONALITY / DEMAND_SEASONALITY.mean() - 1
        year_idx = self.dates.year - self.dates.year[0]
        year_amp = self.rng.normal(1.0, 0.15, year_idx.max() + 1)[year_idx]
        seasonal = 1 + self.season * year_amp * base_season[self.month - 1]
        shocks = self._shock_multiplier()
        tkm = (cfg.base_tkm * np.exp(trend + cycle + contracts + idio)
               * seasonal * shocks)
        return {"freight_volume_tkm": tkm, "demand_idio": idio,
                "demand_seasonal": seasonal}

    def _simulate_mode_mix(self, demand_idio: np.ndarray) -> dict[str, np.ndarray]:
        """Simulates the share of freight moved by road, rail, sea and air.

        Shares are a softmax over mode logits, so they are always positive and
        sum to one. Rail and sea gain share over time (modal shift), air
        spikes in Q4 and during the 2021-22 supply-chain disruption.

        Args:
            demand_idio: Idiosyncratic demand component; demand surprises
                push more urgent freight to air.

        Returns:
            Dict with ``road_share``, ``rail_share``, ``sea_share`` and
            ``air_share``.
        """
        base = np.log([0.78, 0.10, 0.10, 0.02])
        drift = np.array([0.0, 0.035, 0.025, 0.0])
        logits = base + drift * self.years[:, None]

        disruption = self._date_mask("2021-09", "2022-02")
        logits[:, 3] += (0.45 * self.season * self.q4 + 0.50 * disruption
                         + 2.0 * demand_idio)
        logits[:, 1] -= 0.10 * self.season * self.holiday  # rail maintenance
        logits[:, 2] -= 0.20 * disruption
        for k in (1, 2, 3):
            logits[:, k] += self._ar1(phi=0.7, sigma=0.07)

        shares = self._softmax(logits)
        return {f"{m}_share": shares[:, k] for k, m in enumerate(MODES)}

    def _simulate_operations(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Simulates own-fleet road operations: load factor, empty km, km driven.

        The load factor improves slowly (route optimisation) and rises when
        demand is high (trucks fill up). Empty running moves opposite to the
        load factor. Vehicle-km follow from own-fleet tonne-km.

        Args:
            d: Accumulated columns; needs ``freight_volume_tkm``,
                ``road_share`` and ``demand_idio``.

        Returns:
            Dict with ``load_factor``, ``empty_km_ratio``, ``own_fleet_share``,
            ``own_road_tkm`` and ``vehicle_km``.
        """
        q4, holiday, s = self.q4, self.holiday, self.season

        lf_trend = 0.55 + 0.15 * self._logistic((self.calendar_year - 2016.0) / 4.0)
        load_factor = np.clip(
            lf_trend + s * (0.045 * q4 - 0.040 * holiday) + 0.3 * d["demand_idio"]
            + self._ar1(phi=0.7, sigma=0.020),
            0.40, 0.95,
        )
        empty_km = np.clip(
            0.30 - 0.6 * (load_factor - 0.58) + 0.02 * s * holiday
            + self._ar1(phi=0.5, sigma=0.018),
            0.05, 0.50,
        )
        # In peak months the own fleet is saturated, so more is subcontracted.
        own_share = np.clip(
            0.75 - 0.07 * s * q4 + self._ar1(phi=0.6, sigma=0.025), 0.50, 0.90
        )
        own_road_tkm = d["freight_volume_tkm"] * d["road_share"] * own_share
        loaded_km = own_road_tkm / (PAYLOAD_T * load_factor)
        vehicle_km = loaded_km / (1.0 - empty_km)
        return {
            "load_factor": load_factor,
            "empty_km_ratio": empty_km,
            "own_fleet_share": own_share,
            "own_road_tkm": own_road_tkm,
            "vehicle_km": vehicle_km,
        }

    def _simulate_fleet(self, vehicle_km: np.ndarray) -> dict[str, np.ndarray]:
        """Simulates fleet size and EV adoption as integer step functions.

        Trucks are bought in batches when utilisation gets high and sold only
        on semi-annual reviews when the fleet is clearly oversized. EV
        adoption follows an S-curve from 2018 on; the EV count never decreases.

        Args:
            vehicle_km: Monthly kilometres driven by the own fleet.

        Returns:
            Dict with ``fleet_size_total``, ``fleet_ev_count`` and
            ``fleet_ev_share``.
        """
        required = pd.Series(vehicle_km / KM_PER_TRUCK_MONTH).rolling(
            3, min_periods=1
        ).mean().to_numpy()
        fleet = np.empty(self.n, dtype=int)
        current = int(np.ceil(required[0] * 1.10))
        for t in range(self.n):
            if required[t] > current * 0.97:
                current = int(np.ceil(required[t] * 1.08))
            elif required[t] < current * 0.82 and self.month[t] in (1, 7):
                current = int(np.ceil(current * 0.95))
            fleet[t] = current

        target = EV_MAX_SHARE * self._logistic((self.calendar_year - 2024.5) / 1.5)
        target[self.calendar_year < 2017.5] = 0.0
        n_ev = np.maximum.accumulate(np.floor(fleet * target).astype(int))
        n_ev = np.minimum(n_ev, fleet)
        return {
            "fleet_size_total": fleet,
            "fleet_ev_count": n_ev,
            "fleet_ev_share": n_ev / fleet,
        }

    def _simulate_energy(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Simulates warehouse area, diesel, electricity and gas consumption.

        Diesel and EV energy depend on vehicle-km, EV share and seasonally
        varying efficiency (worse in winter). Warehouse electricity scales with
        area and has heating/cooling seasonality. Renewable share moves in
        steps (green tariff, PPA, rooftop solar with summer peaks).

        Args:
            d: Accumulated columns; needs ``freight_volume_tkm``,
                ``vehicle_km`` and ``fleet_ev_share``.

        Returns:
            Dict with energy, warehouse and grid emission factor columns.
        """
        area = self._simulate_warehouse_area(d["freight_volume_tkm"])
        ev_share = d["fleet_ev_share"]

        diesel_l_per_km = (
            0.34 * 0.988 ** self.years * (1 + 0.08 * self.season * self.winter)
            * np.exp(self._ar1(phi=0.5, sigma=0.020))
        )
        ev_kwh_per_km = (1.25 * 0.98 ** (self.calendar_year - 2018)
                         * (1 + 0.22 * self.season * self.winter))
        diesel_l = d["vehicle_km"] * (1 - ev_share) * diesel_l_per_km
        ev_kwh = d["vehicle_km"] * ev_share * ev_kwh_per_km

        warehouse_kwh = (
            area * 8.0 * 0.985 ** self.years
            * (1 + self.season * (0.20 * self.winter + 0.15 * self.summer))
            * np.exp(self._ar1(phi=0.5, sigma=0.030))
        )
        gas_kwh = area * 5.0 * (np.clip(np.cos(2 * np.pi * (self.month - 1) / 12), 0, None)
                                + 0.1) * 0.97 ** self.years

        renewable = np.full(self.n, 0.04)
        for start, step in (("2015-01", 0.08), ("2019-07", 0.25),
                            ("2022-04", 0.12), ("2024-01", 0.15)):
            renewable += step * (self.dates >= pd.Timestamp(start))
        solar_on = self.dates >= pd.Timestamp("2022-04")
        renewable += solar_on * self.season * (0.10 * self.summer - 0.05)
        renewable = np.clip(renewable + self._ar1(phi=0.5, sigma=0.015), 0.0, 1.0)

        grid_ef = (
            self._interp_anchors(GRID_EF_ANCHORS)
            * (1 + self.season * (0.08 * self.winter - 0.04))
            * np.exp(self._ar1(phi=0.6, sigma=0.03))
        )
        return {
            "warehouse_area_m2": area,
            "diesel_consumption_l": diesel_l,
            "electricity_consumption_kwh": warehouse_kwh + ev_kwh,
            "gas_consumption_kwh": gas_kwh,
            "renewable_energy_share": renewable,
            "grid_emission_factor_kg_per_kwh": grid_ef,
        }

    def _simulate_warehouse_area(self, tkm: np.ndarray) -> np.ndarray:
        """Simulates warehouse floor area that expands in discrete steps.

        Args:
            tkm: Monthly freight volume in tonne-km.

        Returns:
            Warehouse area in m2; never decreases and grows in 5,000 m2 units.
        """
        scale = self.config.base_tkm / 25e6
        area0 = WAREHOUSE_AREA0_M2 * scale
        tkm_per_m2 = self.config.base_tkm / (area0 * 0.85)
        needed = pd.Series(tkm).rolling(6, min_periods=1).mean().to_numpy() / tkm_per_m2
        area = np.empty(self.n)
        current = area0
        for t in range(self.n):
            if needed[t] > current * 0.92:
                current = np.ceil(current * 1.15 / 5_000) * 5_000
            area[t] = current
        return area

    def _simulate_market_prices(self) -> dict[str, np.ndarray]:
        """Simulates diesel, electricity and carbon prices.

        Each price follows yearly anchors (interpolated monthly) multiplied by
        a persistent AR(1) shock in log space, so prices are non-negative and
        volatile without drifting away from the historic path.

        Returns:
            Dict with ``diesel_price_eur_per_l``,
            ``electricity_price_eur_per_kwh`` and ``carbon_price_eur_per_t``.
        """
        diesel = self._interp_anchors(DIESEL_PRICE_ANCHORS) * np.exp(
            self._ar1(phi=0.8, sigma=0.045))
        elec = self._interp_anchors(ELECTRICITY_PRICE_ANCHORS) * np.exp(
            self._ar1(phi=0.8, sigma=0.06))
        carbon = self._interp_anchors(CARBON_PRICE_ANCHORS) * np.exp(
            self._ar1(phi=0.85, sigma=0.10))
        return {
            "diesel_price_eur_per_l": diesel,
            "electricity_price_eur_per_kwh": elec,
            "carbon_price_eur_per_t": carbon,
        }

    def _simulate_direct_emissions(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Computes scope 1 and scope 2 (market-based) emissions.

        Scope 1 = diesel + gas combustion + refrigerant leakage (with rare
        leak events). Scope 2 = electricity x grid factor x non-renewable share.

        Args:
            d: Accumulated columns with energy use and grid factor.

        Returns:
            Dict with ``scope1_tco2e`` and ``scope2_tco2e``.
        """
        leaks = (self.rng.random(self.n) < 0.03) * self.rng.uniform(5, 20, self.n)
        refrigerant_t = d["warehouse_area_m2"] * 2e-5 + leaks
        scope1 = (
            d["diesel_consumption_l"] * EF_DIESEL_KG_PER_L
            + d["gas_consumption_kwh"] * EF_GAS_KG_PER_KWH
        ) / 1000.0 + refrigerant_t
        scope2 = (
            d["electricity_consumption_kwh"] * d["grid_emission_factor_kg_per_kwh"]
            * (1 - d["renewable_energy_share"]) / 1000.0
        )
        return {"scope1_tco2e": scope1, "scope2_tco2e": scope2}

    def _simulate_green_capex(self, n_ev: np.ndarray) -> dict[str, np.ndarray]:
        """Simulates lumpy green investments.

        Includes e-truck purchases (cheaper every year), a LED retrofit, a
        rooftop solar installation and small random efficiency projects.

        Args:
            n_ev: Monthly number of electric trucks in the fleet.

        Returns:
            Dict with ``green_capex_eur``.
        """
        new_ev = np.diff(n_ev, prepend=n_ev[0])
        capex = new_ev * EV_TRUCK_COST_EUR * 0.95 ** (self.calendar_year - 2018)
        capex += 400_000 * self._date_mask("2016-03", "2016-03")
        capex += 750_000 * self._date_mask("2022-02", "2022-03")  # solar install
        small = self.rng.random(self.n) < 0.08
        capex += small * self.rng.lognormal(np.log(50_000), 0.5, self.n)
        return {"green_capex_eur": capex}

    def _simulate_financials(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Computes revenue, operating cost and EBITDA.

        Revenue = freight rates x tonne-km by mode (with inflation, fuel
        surcharge, peak premium and pricing noise) + warehousing fees.
        Operating cost = fuel + energy + labour + subcontracting + maintenance
        + warehouse opex + overhead + carbon cost. The partly fixed overhead
        gives economies of scale, so margins improve as the company grows.

        Args:
            d: Accumulated columns with volumes, fleet, energy, prices and
                scope 1 emissions.

        Returns:
            Dict with ``revenue_eur``, ``operating_cost_eur``, ``ebitda_eur``
            and the internal ``purchased_spend_eur`` used for scope 3.
        """
        inflation = 1.022 ** self.years
        # Competitive pressure: freight rates rise slower than input costs.
        rate_index = 1.016 ** self.years
        wage_index = 1.03 ** self.years
        diesel_lag = np.roll(d["diesel_price_eur_per_l"], 1)
        diesel_lag[0] = d["diesel_price_eur_per_l"][0]
        # Surcharges are indexed to the recent (24-month) diesel price level.
        diesel_ref = pd.Series(d["diesel_price_eur_per_l"]).rolling(
            24, min_periods=1).mean().to_numpy()
        surcharge = 1 + 0.30 * (diesel_lag / diesel_ref - 1)
        q4 = np.isin(self.month, [10, 11, 12])

        tkm = d["freight_volume_tkm"]
        mode_tkm = {m: tkm * d[f"{m}_share"] for m in MODES}
        sub_tkm = dict(mode_tkm, road=mode_tkm["road"] - d["own_road_tkm"])

        transport_rev = sum(mode_tkm[m] * FREIGHT_RATE_EUR_PER_TKM[m] for m in MODES)
        transport_rev *= rate_index * surcharge * (1 + 0.05 * self.season * q4) * np.exp(
            self._ar1(phi=0.7, sigma=0.025))
        area = d["warehouse_area_m2"]
        tkm_per_m2 = self.config.base_tkm / (area[0] * 0.85)
        utilisation = np.clip(tkm / (area * tkm_per_m2), 0, 1.2)
        warehouse_rev = area * 6.0 * rate_index * (0.85 + 0.15 * utilisation)
        revenue = transport_rev + warehouse_rev

        ev = d["fleet_ev_share"]
        renew = d["renewable_energy_share"]
        ppa_price = 0.085 * inflation
        fuel = d["diesel_consumption_l"] * d["diesel_price_eur_per_l"]
        energy = d["electricity_consumption_kwh"] * (
            (1 - renew) * d["electricity_price_eur_per_kwh"] + renew * ppa_price)
        gas = d["gas_consumption_kwh"] * 0.45 * d["electricity_price_eur_per_kwh"]
        # 40% of labour is flexible (temp staff, overtime) and follows the season.
        flex = 0.60 + 0.40 * d["demand_seasonal"]
        labour = (d["fleet_size_total"] * 3_000 + area * 1.2) * wage_index * flex
        subcontract = sum(sub_tkm[m] * SUBCONTRACT_COST_EUR_PER_TKM[m] for m in MODES)
        subcontract *= inflation * (1 + 0.25 * (diesel_lag / diesel_ref - 1))
        maintenance = d["vehicle_km"] * ((1 - ev) * 0.12 + ev * 0.07) * inflation
        warehouse_opex = area * 3.0 * inflation
        overhead = 150_000 * inflation + 0.035 * revenue
        coverage = 0.3 + 0.7 * np.clip((self.calendar_year - 2021) / 2, 0, 1)
        carbon_cost = d["scope1_tco2e"] * d["carbon_price_eur_per_t"] * coverage

        opex = (fuel + energy + gas + labour + subcontract + maintenance
                + warehouse_opex + overhead + carbon_cost)
        return {
            "revenue_eur": revenue,
            "operating_cost_eur": opex,
            "ebitda_eur": revenue - opex,
            "purchased_spend_eur": maintenance + warehouse_opex + overhead,
        }

    def _simulate_scope3(self, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Computes scope 3 emissions.

        Covers subcontracted transport by mode (cat. 4), well-to-tank fuel and
        electricity emissions (cat. 3) and spend-based purchased goods and
        services (cat. 1).

        Args:
            d: Accumulated columns with volumes, energy and spend.

        Returns:
            Dict with ``scope3_tco2e``.
        """
        tkm = d["freight_volume_tkm"]
        sub_road = tkm * d["road_share"] - d["own_road_tkm"]
        transport_kg = sub_road * EF_SUBCONTRACT_KG_PER_TKM["road"] + sum(
            tkm * d[f"{m}_share"] * EF_SUBCONTRACT_KG_PER_TKM[m]
            for m in ("rail", "sea", "air"))
        wtt_kg = (d["diesel_consumption_l"] * EF_DIESEL_WTT_KG_PER_L
                  + d["electricity_consumption_kwh"] * EF_ELEC_WTT_KG_PER_KWH)
        spend_kg = d["purchased_spend_eur"] * EF_SPEND_KG_PER_EUR
        return {"scope3_tco2e": (transport_kg + wtt_kg + spend_kg) / 1000.0}

    def _to_frame(self, d: dict[str, np.ndarray]) -> pd.DataFrame:
        """Assembles the output DataFrame in a fixed column order.

        Internal helper arrays (latent components, own-fleet tonne-km, gas,
        spend) are dropped.

        Args:
            d: All simulated arrays.

        Returns:
            DataFrame with a ``date`` column followed by the output features.
        """
        columns = [
            "revenue_eur", "operating_cost_eur", "ebitda_eur",
            "freight_volume_tkm", "road_share", "rail_share", "sea_share", "air_share",
            "fleet_size_total", "fleet_ev_count", "fleet_ev_share",
            "load_factor", "empty_km_ratio", "vehicle_km",
            "diesel_consumption_l", "electricity_consumption_kwh",
            "renewable_energy_share", "warehouse_area_m2",
            "grid_emission_factor_kg_per_kwh", "diesel_price_eur_per_l",
            "electricity_price_eur_per_kwh", "carbon_price_eur_per_t",
            "scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "total_emissions_tco2e",
            "green_capex_eur",
        ]
        df = pd.DataFrame({"date": self.dates})
        for col in columns:
            df[col] = d[col]
        return df

    # ------------------------------------------------------------------ #
    # Measurement layer (column-specific noise)
    # ------------------------------------------------------------------ #

    def _apply_measurement_noise(self, clean: pd.DataFrame) -> pd.DataFrame:
        """Adds noise to each column according to how it is recorded.

        * Transport-system and financial data: small multiplicative noise.
        * Invoiced amounts: timing noise (accruals shifted between months,
          totals preserved).
        * Fuel cards / meters: larger multiplicative noise; utility bills are
          sometimes estimated and reconciled the following month.
        * Shares and ratios: noise in logit space so they stay in (0, 1);
          mode shares are renormalised to sum to one.
        * Counts: occasional integer registry errors.
        * Grid factor: published annually with a one-year lag.
        * Market prices: no noise, only rounding.
        * Emissions: recomputed or scaled from the noisy activity data; scope 3
          carries a persistent estimation bias and is only estimated annually
          in early years.

        Args:
            clean: Ground-truth dataset.

        Returns:
            Dataset as it would be reported by the company (an unchanged copy
            of ``clean`` when ``noise_level`` is 0).
        """
        lvl = self.config.noise_level
        out = clean.copy()
        if lvl <= 0:
            return out

        out["freight_volume_tkm"] = self._lognormal_noise(clean["freight_volume_tkm"], 0.02 * lvl)
        out["vehicle_km"] = self._lognormal_noise(clean["vehicle_km"], 0.035 * lvl)

        shares = np.column_stack([
            self._logit_noise(clean[f"{m}_share"], 0.08 * lvl) for m in MODES])
        shares /= shares.sum(axis=1, keepdims=True)
        for k, m in enumerate(MODES):
            out[f"{m}_share"] = shares[:, k]
        out["load_factor"] = self._logit_noise(clean["load_factor"], 0.10 * lvl)
        out["empty_km_ratio"] = self._logit_noise(clean["empty_km_ratio"], 0.15 * lvl)
        out["renewable_energy_share"] = self._logit_noise(
            clean["renewable_energy_share"], 0.04 * lvl)

        fleet = self._count_noise(clean["fleet_size_total"], prob=0.10 * lvl, max_err=4)
        ev = self._count_noise(clean["fleet_ev_count"], prob=0.06 * lvl, max_err=1)
        ev = np.where(clean["fleet_ev_count"] == 0, 0, np.clip(ev, 0, fleet))
        out["fleet_size_total"], out["fleet_ev_count"] = fleet, ev
        out["fleet_ev_share"] = ev / fleet

        diesel = self._lognormal_noise(clean["diesel_consumption_l"], 0.05 * lvl)
        out["diesel_consumption_l"] = diesel
        elec = self._lognormal_noise(clean["electricity_consumption_kwh"], 0.03 * lvl)
        out["electricity_consumption_kwh"] = self._estimated_readings(elec, prob=0.10 * lvl)

        out["grid_emission_factor_kg_per_kwh"] = self._annual_published_factor(
            clean["grid_emission_factor_kg_per_kwh"])

        out["diesel_price_eur_per_l"] = clean["diesel_price_eur_per_l"].round(3)
        out["electricity_price_eur_per_kwh"] = clean["electricity_price_eur_per_kwh"].round(3)
        out["carbon_price_eur_per_t"] = clean["carbon_price_eur_per_t"].round(2)

        diesel_ratio = diesel / clean["diesel_consumption_l"]
        out["scope1_tco2e"] = self._lognormal_noise(
            clean["scope1_tco2e"] * diesel_ratio ** 0.9, 0.02 * lvl)
        out["scope2_tco2e"] = (
            out["electricity_consumption_kwh"] * out["grid_emission_factor_kg_per_kwh"]
            * (1 - out["renewable_energy_share"]) / 1000.0)
        scope3 = clean["scope3_tco2e"] * np.exp(self._ar1(phi=0.8, sigma=0.12 * lvl))
        out["scope3_tco2e"] = self._annual_estimate(scope3, self.dates.year < 2015)
        out["total_emissions_tco2e"] = (
            out["scope1_tco2e"] + out["scope2_tco2e"] + out["scope3_tco2e"])

        revenue = self._lognormal_noise(clean["revenue_eur"], 0.010 * lvl)
        opex = self._lognormal_noise(clean["operating_cost_eur"], 0.015 * lvl)
        out["revenue_eur"] = self._timing_noise(revenue, prob=0.12 * lvl, max_frac=0.08)
        out["operating_cost_eur"] = self._timing_noise(opex, prob=0.14 * lvl, max_frac=0.08)
        out["ebitda_eur"] = out["revenue_eur"] - out["operating_cost_eur"]
        out["green_capex_eur"] = self._timing_noise(
            clean["green_capex_eur"], prob=0.15 * lvl, max_frac=0.30)
        return out

    def _lognormal_noise(self, x: pd.Series | np.ndarray, sigma: float) -> np.ndarray:
        """Applies mean-preserving multiplicative log-normal noise.

        Args:
            x: Strictly positive values.
            sigma: Standard deviation of the noise in log space (~relative error).

        Returns:
            Noisy values, still strictly positive.
        """
        x = np.asarray(x, dtype=float)
        return x * np.exp(self.rng.normal(-0.5 * sigma ** 2, sigma, x.shape))

    def _logit_noise(self, p: pd.Series | np.ndarray, sigma: float) -> np.ndarray:
        """Adds Gaussian noise in logit space to keep values inside (0, 1).

        Args:
            p: Proportions in [0, 1].
            sigma: Noise standard deviation in logit space.

        Returns:
            Noisy proportions strictly inside (0, 1).
        """
        p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
        z = np.log(p / (1 - p)) + self.rng.normal(0, sigma, p.shape)
        return self._logistic(z)

    def _count_noise(self, x: pd.Series | np.ndarray, prob: float, max_err: int) -> np.ndarray:
        """Adds occasional integer errors to a count column.

        Args:
            x: Non-negative integer counts.
            prob: Probability that a month's count is misreported.
            max_err: Maximum absolute size of an error.

        Returns:
            Noisy non-negative integer counts.
        """
        x = np.asarray(x, dtype=int)
        hit = self.rng.random(x.shape) < min(prob, 1.0)
        err = self.rng.integers(-max_err, max_err + 1, x.shape)
        return np.maximum(x + hit * err, 0)

    def _timing_noise(self, x: pd.Series | np.ndarray, prob: float, max_frac: float) -> np.ndarray:
        """Shifts part of a month's amount into the next month (late booking).

        The total over the series is preserved, mimicking accrual and
        invoice-timing effects in accounting data.

        Args:
            x: Monthly amounts.
            prob: Probability that a given month has a late booking.
            max_frac: Maximum fraction of the month's amount that is shifted.

        Returns:
            Amounts with timing noise.
        """
        x = np.asarray(x, dtype=float).copy()
        for t in range(len(x) - 1):
            if self.rng.random() < prob:
                moved = x[t] * self.rng.uniform(0, max_frac)
                x[t] -= moved
                x[t + 1] += moved
        return x

    def _estimated_readings(self, x: np.ndarray, prob: float) -> np.ndarray:
        """Replaces some readings with utility estimates reconciled next month.

        An estimated month is set to the mean of the previous three months; the
        difference to the true reading is added to the following month.

        Args:
            x: Monthly metered consumption.
            prob: Probability that a month is estimated rather than read.

        Returns:
            Consumption series with estimated-and-reconciled months.
        """
        x = x.copy()
        for t in range(3, len(x) - 1):
            if self.rng.random() < prob:
                estimate = x[t - 3:t].mean()
                x[t + 1] += x[t] - estimate
                x[t] = estimate
        return x

    def _annual_published_factor(self, factor: pd.Series) -> np.ndarray:
        """Converts a monthly factor into an annually published, lagged value.

        Official grid factors are published once a year for the previous
        year, so reporting uses last year's annual mean (the first year uses
        its own mean).

        Args:
            factor: True monthly grid emission factor.

        Returns:
            Factor as used in reporting, constant within each calendar year.
        """
        years = self.dates.year
        annual = pd.Series(np.asarray(factor)).groupby(years).mean()
        lagged = annual.shift(1).fillna(annual.iloc[0])
        return lagged.loc[years].to_numpy()

    def _annual_estimate(self, x: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Replaces masked months by their calendar-year average.

        Mimics early-year reporting where a quantity was only estimated once a
        year and spread evenly over the months.

        Args:
            x: Monthly values.
            mask: Boolean array; True where values are annual estimates.

        Returns:
            Series with flat annual values in the masked months.
        """
        s = pd.Series(np.asarray(x, dtype=float))
        annual_mean = s.groupby(self.dates.year).transform("mean").to_numpy()
        return np.where(mask, annual_mean, s.to_numpy())

    # ------------------------------------------------------------------ #
    # Visualisation
    # ------------------------------------------------------------------ #

    def plot_column(
        self,
        column: str,
        df: pd.DataFrame | None = None,
        show_clean: bool = True,
        ax: plt.Axes | None = None,
        legend: bool = True,
    ) -> plt.Axes:
        """Plots the monthly time series of a single column.

        The reported (noisy) series is drawn on top of the ground truth so
        the effect of measurement noise is visible.

        Args:
            column: Name of the column to plot.
            df: Dataset to plot. Defaults to the last noisy dataset.
            show_clean: Whether to overlay the ground-truth series.
            ax: Axes to draw on. A new figure is created when omitted.
            legend: Whether to draw a legend on the axes.

        Returns:
            The axes containing the plot.
        """
        df = self._resolve_data(df)
        if ax is None:
            _, ax = plt.subplots(figsize=(10, 3.5))
        clean = self.clean_data_
        if show_clean and clean is not None and column in clean:
            ax.plot(clean["date"], clean[column], color=COLOR_CLEAN,
                    lw=1.0, label="Ground truth")
        ax.plot(df["date"], df[column], color=COLOR_REPORTED, lw=1.6,
                label="Reported")
        self._style_axis(ax, column)
        if legend and show_clean and clean is not None:
            ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower right",
                      bbox_to_anchor=(1.0, 1.0))
        return ax

    def plot_time_series(
        self,
        df: pd.DataFrame | None = None,
        columns: list[str] | None = None,
        show_clean: bool = True,
        ncols: int = 3,
    ) -> plt.Figure:
        """Plots the time series of every column as a grid of small multiples.

        Each column gets its own panel and y-scale, so magnitudes are never
        compared across different units.

        Args:
            df: Dataset to plot. Defaults to the last noisy dataset.
            columns: Columns to plot. Defaults to all columns except ``date``.
            show_clean: Whether to overlay the ground-truth series.
            ncols: Number of panels per row.

        Returns:
            The figure containing all panels.
        """
        df = self._resolve_data(df)
        columns = columns or [c for c in df.columns if c != "date"]
        nrows = int(np.ceil(len(columns) / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 2.6 * nrows),
                                 sharex=True, squeeze=False)
        for ax, col in zip(axes.flat, columns):
            self.plot_column(col, df=df, show_clean=show_clean, ax=ax, legend=False)
        for ax in axes.flat[len(columns):]:
            ax.set_visible(False)
        handles, labels = axes.flat[0].get_legend_handles_labels()
        if len(handles) > 1:
            fig.legend(handles, labels, loc="upper center", ncol=len(handles),
                       frameon=False, bbox_to_anchor=(0.5, 1.0))
        fig.suptitle("Monthly time series per feature", y=1.015,
                     fontsize=14, color=COLOR_INK)
        fig.tight_layout(rect=(0, 0, 1, 0.99))
        return fig

    def plot_correlation_heatmap(
        self,
        df: pd.DataFrame | None = None,
        columns: list[str] | None = None,
        transform: str = "level",
        method: str = "pearson",
    ) -> plt.Figure:
        """Plots a lower-triangle correlation heatmap of the numeric features.

        Constant columns are dropped, and the target columns
        (:data:`TARGET_COLUMNS`) are placed first and shown in bold.

        Because most features share the growth trend, correlations of the raw
        levels are close to 1 almost everywhere. ``transform="yoy_change"``
        correlates 12-month differences instead, which removes trend and
        seasonality and shows the month-to-month relationships.

        Args:
            df: Dataset to analyse. Defaults to the last noisy dataset.
            columns: Columns to include. Defaults to all numeric columns.
            transform: ``"level"`` for raw values or ``"yoy_change"`` for
                year-over-year differences.
            method: Correlation method passed to :meth:`pandas.DataFrame.corr`.

        Returns:
            The heatmap figure.

        Raises:
            ValueError: If ``transform`` is not supported.
        """
        df = self._resolve_data(df)
        num = df.drop(columns="date").select_dtypes("number")
        if columns:
            num = num[columns]
        if transform == "yoy_change":
            num = num.diff(12)
        elif transform != "level":
            raise ValueError(f"Unsupported transform: {transform!r}")
        num = num.loc[:, num.std() > 0]
        targets = [c for c in TARGET_COLUMNS if c in num]
        num = num[targets + [c for c in num if c not in targets]]
        corr = num.corr(method=method)

        n = len(corr)
        masked = np.ma.masked_where(np.triu(np.ones((n, n), dtype=bool), k=1),
                                    corr.to_numpy())
        fig, ax = plt.subplots(figsize=(0.42 * n + 3, 0.42 * n + 1.5))
        im = ax.imshow(masked, cmap=DIVERGING_CMAP, vmin=-1, vmax=1)
        for i in range(n):
            for j in range(i + 1):
                v = corr.iat[i, j]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6,
                        color="white" if abs(v) > 0.6 else COLOR_INK)
        ax.set_xticks(range(n), corr.columns, rotation=90, fontsize=8)
        ax.set_yticks(range(n), corr.columns, fontsize=8)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            if label.get_text() in targets:
                label.set_fontweight("bold")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(length=0)
        cbar = fig.colorbar(im, ax=ax, shrink=0.6)
        cbar.set_label(f"{method.capitalize()} correlation", color=COLOR_INK)
        cbar.outline.set_visible(False)
        title = {"level": "levels", "yoy_change": "year-over-year changes"}[transform]
        ax.set_title(f"Feature correlations ({title}); targets in bold",
                     fontsize=13, color=COLOR_INK, loc="left")
        fig.tight_layout()
        return fig

    def _resolve_data(self, df: pd.DataFrame | None) -> pd.DataFrame:
        """Returns the given dataset or falls back to the last noisy dataset.

        Args:
            df: Dataset passed by the caller, or ``None``.

        Returns:
            The dataset to plot.

        Raises:
            RuntimeError: If no dataset was given and :meth:`generate` has not
                been called yet.
        """
        if df is not None:
            return df
        if self.noisy_data_ is None:
            raise RuntimeError("No data available; call generate() first.")
        return self.noisy_data_

    @staticmethod
    def _style_axis(ax: plt.Axes, column: str) -> None:
        """Applies the shared look to a time-series axis.

        Shares and ratios get a percentage axis; large values use
        engineering notation (k, M, G); small values keep plain numbers.

        Args:
            ax: Axes to style (already containing the plotted data).
            column: Column name, used as the title and to choose the formatter.
        """
        ax.set_title(column, fontsize=10, color=COLOR_INK, loc="left")
        if column.endswith("_share") or column in ("load_factor", "empty_km_ratio"):
            ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        elif max(abs(v) for v in ax.get_ylim()) >= 1_000:
            ax.yaxis.set_major_formatter(EngFormatter())
        ax.grid(axis="y", color=COLOR_GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(COLOR_GRID)
        ax.tick_params(colors=COLOR_INK_MUTED, labelsize=8)

    # ------------------------------------------------------------------ #
    # Generic helpers
    # ------------------------------------------------------------------ #

    def _ar1(self, phi: float, sigma: float) -> np.ndarray:
        """Generates a stationary zero-mean AR(1) series.

        Args:
            phi: Autocorrelation coefficient in [0, 1).
            sigma: Stationary standard deviation of the series.

        Returns:
            Array of length ``self.n``.
        """
        eps = self.rng.normal(0.0, sigma * np.sqrt(1 - phi ** 2), self.n)
        x = np.empty(self.n)
        x[0] = self.rng.normal(0.0, sigma)
        for t in range(1, self.n):
            x[t] = phi * x[t - 1] + eps[t]
        return x

    def _shock_multiplier(self) -> np.ndarray:
        """Looks up the macro demand shock for each month.

        Returns:
            Multiplicative shock per month (1.0 where there is no shock).
        """
        keys = self.dates.strftime("%Y-%m")
        return np.array([DEMAND_SHOCKS.get(k, 1.0) for k in keys])

    def _date_mask(self, start: str, end: str) -> np.ndarray:
        """Builds a boolean mask for an inclusive range of months.

        Args:
            start: First month, ``YYYY-MM``.
            end: Last month, ``YYYY-MM``.

        Returns:
            Boolean array, True for months within ``[start, end]``.
        """
        return np.asarray((self.dates >= pd.Timestamp(start))
                          & (self.dates <= pd.Timestamp(end)))

    def _interp_anchors(self, anchors: dict[int, float]) -> np.ndarray:
        """Interpolates yearly anchor values to monthly resolution.

        Anchors sit in the middle of their year; values outside the anchor
        range are held constant.

        Args:
            anchors: Mapping from calendar year to value.

        Returns:
            Monthly interpolated values.
        """
        xs = np.array(sorted(anchors)) + 0.5
        ys = np.array([anchors[y] for y in sorted(anchors)])
        return np.interp(self.calendar_year, xs, ys)

    @staticmethod
    def _logistic(x: np.ndarray) -> np.ndarray:
        """Standard logistic function.

        Args:
            x: Input values.

        Returns:
            Values in (0, 1).
        """
        return 1.0 / (1.0 + np.exp(-x))

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        """Row-wise softmax.

        Args:
            logits: 2-D array of shape (n, k).

        Returns:
            Array of the same shape whose rows are positive and sum to one.
        """
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)


if __name__ == "__main__":
    plt.switch_backend("Agg")  # render to files without a display
    output_dir = Path(__file__).resolve().parent / "temp_outputs"
    series_dir = output_dir / "time_series"
    series_dir.mkdir(parents=True, exist_ok=True)

    generator = SupplyChainDataGenerator()
    data = generator.generate()

    for col in data.columns.drop("date"):
        ax = generator.plot_column(col)
        ax.figure.savefig(series_dir / f"{col}.png", dpi=150, bbox_inches="tight")
        plt.close(ax.figure)

    fig = generator.plot_time_series()
    fig.savefig(output_dir / "time_series_all.png", dpi=120, bbox_inches="tight")
    plt.close(fig)

    for transform in ("level", "yoy_change"):
        fig = generator.plot_correlation_heatmap(transform=transform)
        fig.savefig(output_dir / f"correlation_heatmap_{transform}.png",
                    dpi=150, bbox_inches="tight")
        plt.close(fig)

    print(f"Saved visualisations to {output_dir}")
