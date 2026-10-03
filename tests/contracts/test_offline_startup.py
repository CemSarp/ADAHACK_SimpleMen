"""P0 imports and startup need no optional dependency, network or model file.

Each check runs in a fresh interpreter with a meta-path blocker for optional
libraries and a socket guard, so results do not depend on what the developer
happens to have installed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

GUARD = textwrap.dedent(
    """
    import importlib.abc, socket, sys
    BLOCKED = {"lightgbm", "xgboost", "shap", "pymoo", "scipy", "sklearn", "requests", "openai", "anthropic"}

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ModuleNotFoundError(f"blocked optional dependency: {name}", name=name)
            return None

    sys.meta_path.insert(0, Blocker())
    for mod in list(sys.modules):
        if mod.split(".")[0] in BLOCKED:
            del sys.modules[mod]

    def _no_network(*args, **kwargs):
        raise RuntimeError("network access attempted during P0 startup")

    socket.socket.connect = _no_network
    socket.create_connection = _no_network
    """
)


def _run(body: str) -> subprocess.CompletedProcess:
    code = GUARD + textwrap.dedent(body)
    return subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)


def test_contracts_import_without_streamlit_or_optional_libraries():
    proc = _run(
        """
        import src.contracts, src.integration
        assert "streamlit" not in sys.modules, "contracts/integration must not import Streamlit"
        assert "plotly" not in sys.modules
        print("ok")
        """
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_mock_pipeline_runs_offline_without_optional_libraries():
    proc = _run(
        """
        from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig
        from src.integration import create_services, run_analysis
        services = create_services(mode="mock")
        bundle = run_analysis(AnalysisRequest(company_id="demo-company", horizon_months=12,
            constraints=ConstraintConfig(500000.0, 1000000.0, 0.2), optimizer_config=OptimizerConfig(max_evaluations=64),
            risk_enabled=True, benchmark_enabled=True, explanation_enabled=True), services=services)
        assert bundle.provenance.is_mock and bundle.optimization.status == "ok"
        print("ok")
        """
    )
    assert proc.returncode == 0, proc.stderr


def test_streamlit_app_starts_offline_in_mock_mode():
    proc = _run(
        """
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file("app.py", default_timeout=120).run()
        assert not at.exception, [e.message for e in at.exception]
        assert any("MOCK OUTPUT" in w.value for w in at.warning)
        print("ok")
        """
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_real_mode_reports_missing_p0_providers_without_crashing_the_app():
    # The guard blocks pymoo, so this checks both missing-provider reasons: WS1's forecast
    # module does not exist, and WS2's optimizer cannot load its solver dependency.
    proc = _run(
        """
        import os
        os.environ["CARBONOPT_PROVIDER_MODE"] = "real"
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file("app.py", default_timeout=120).run()
        assert not at.exception, [e.message for e in at.exception]
        errors = [e.value for e in at.error]
        assert any("Provider configuration error" in e and "forecast" in e for e in errors), errors
        assert any("missing dependency: pymoo" in e for e in errors), errors
        assert not any("MOCK OUTPUT" in w.value or "PARTIALLY MOCKED" in w.value for w in at.warning)
        print("ok")
        """
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
