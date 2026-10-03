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
    proc = _run(
        """
        import os
        os.environ["CARBONOPT_PROVIDER_MODE"] = "real"
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file("app.py", default_timeout=120).run()
        assert not at.exception, [e.message for e in at.exception]
        errors = [e.value for e in at.error]
        assert any("Provider configuration error" in e and "simulator" in e for e in errors), errors
        assert not any("MOCK OUTPUT" in w.value for w in at.warning)
        print("ok")
        """
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_chat_modules_import_and_mock_chat_runs_offline_without_optional_libraries():
    proc = _run(
        """
        import src.llm, src.llm.providers, src.llm.assistant, src.llm.tools
        assert "streamlit" not in sys.modules, "src.llm must not import Streamlit"
        assert "requests" not in sys.modules
        from src.contracts.types import AnalysisRequest, ConstraintConfig, OptimizerConfig
        from src.integration import create_services, run_analysis
        from src.llm.assistant import TurnRecord, run_turn
        from src.llm.config import ChatbotConfig
        from src.llm.context import AnalysisContext
        from src.llm.providers import create_chat_provider
        provider = create_chat_provider(ChatbotConfig.from_env({}))
        assert provider.info.is_mock
        services = create_services(mode="mock")
        req = AnalysisRequest(company_id="demo-company", horizon_months=12,
                              constraints=ConstraintConfig(500000.0, 1000000.0, 0.2), optimizer_config=OptimizerConfig(max_evaluations=64))
        a = run_analysis(req, services=services)
        ctx = AnalysisContext(services, req, a.baseline, a, None)
        out = run_turn(provider=provider, history=[], user_text="Show the baseline forecast.", context=ctx, record=TurnRecord())
        assert "1,200.0 tCO2e" in out.text
        print("ok")
        """
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_ollama_provider_makes_no_request_until_called():
    proc = _run(
        """
        from src.llm.config import ChatbotConfig
        from src.llm.providers import create_chat_provider
        p = create_chat_provider(ChatbotConfig.from_env({"CHATBOT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://llm.example.test"}))
        assert not p.info.is_mock
        try:
            p.check_connection()
        except RuntimeError as exc:  # the guard's network error is surfaced as a typed provider error, not hidden
            print("failed-visibly")
        """
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "failed-visibly"
