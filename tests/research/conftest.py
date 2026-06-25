"""Phase 92 Plan 03 — conftest for the research classification harness.

Provides:
- ``golden_link_set`` fixture loading the 30-doc labelled set
- ``mock_llm_client``  fixture providing a deterministic LLM stub
- ``mock_economic_indicator_catalog`` returning a locked 64-ID FRED catalog
  matching the Phase 83 schema (used to validate expected_indicators in labels.yaml)

These fixtures are deliberately host-shell-friendly: no Django setup, no
network calls, no cross-VM filesystem reads. The harness can therefore run
under ``pytest -m phase92`` directly from VM107's pytest.ini.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

# ── Filesystem anchors ─────────────────────────────────────────────────
_VM107_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_ROOT = _VM107_ROOT / "tests" / "research" / "fixtures" / "golden_link_set"
_DATA_ROOT = _VM107_ROOT / "data"


# ── 30-doc golden labelled set ─────────────────────────────────────────
@dataclass(frozen=True)
class GoldenDoc:
    doc_id: str
    source: str
    text: str
    expected_indicators: list[str]
    expected_assets: list[str]
    expected_tier: int
    expected_status: str
    expected_linker_stage: str


@pytest.fixture(scope="session")
def golden_link_set() -> list[GoldenDoc]:
    """Load + parse labels.yaml; attach .text from the matching .txt fixture."""
    labels_path = _FIXTURES_ROOT / "labels.yaml"
    raw = yaml.safe_load(labels_path.read_text())
    out: list[GoldenDoc] = []
    for entry in raw["docs"]:
        text_path = _FIXTURES_ROOT / f"{entry['doc_id']}.txt"
        assert text_path.exists(), f"Missing fixture: {text_path}"
        text = text_path.read_text()
        out.append(
            GoldenDoc(
                doc_id=entry["doc_id"],
                source=entry["source"],
                text=text,
                expected_indicators=list(entry["expected_indicators"]),
                expected_assets=list(entry["expected_assets"]),
                expected_tier=int(entry["expected_tier"]),
                expected_status=entry["expected_status"],
                expected_linker_stage=entry["expected_linker_stage"],
            )
        )
    return out


# ── Mock LLM client ────────────────────────────────────────────────────
class MockLLMClient:
    """Deterministic LLM stub for Stage 2 indicator-linker tests.

    The real LLM client (VM107/services/llm_client.py) is litellm-routed and
    needs LLM_MODEL + LLM_API_KEY. For tests we want determinism:

    - ``MockLLMClient.classify(doc_text, doc_title, candidate_indicators)``
      returns a list of (indicator_id, confidence) tuples, configured via
      ``MockLLMClient.set_response(...)``.

    - Default behavior: returns ``[]`` (LLM finds no link).
    """

    def __init__(self) -> None:
        self._responses: dict[str, list[dict[str, Any]]] = {}
        self._default_response: list[dict[str, Any]] = []
        self.call_log: list[dict[str, Any]] = []

    def set_response(self, key: str, response: list[dict[str, Any]]) -> None:
        self._responses[key] = response

    def set_default(self, response: list[dict[str, Any]]) -> None:
        self._default_response = response

    def classify(
        self,
        doc_text: str,
        doc_title: str,
        candidate_indicators: list[str],
    ) -> list[dict[str, Any]]:
        self.call_log.append(
            {
                "doc_text_len": len(doc_text),
                "doc_title": doc_title,
                "candidates": list(candidate_indicators),
            }
        )
        # Match by doc_title substring first
        for key, resp in self._responses.items():
            if key in doc_title or key in doc_text[:300]:
                return resp
        return list(self._default_response)


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    return MockLLMClient()


# ── Locked FRED catalog (Phase 83) ─────────────────────────────────────
# Subset of the 64-ID Phase 83 catalog covering every indicator id used in
# labels.yaml + indicator_synonyms.yaml. The host-shell harness uses this
# instead of cross-VM hitting the VM100 reference-data API.
_PHASE_83_CATALOG_IDS: tuple[str, ...] = (
    # Inflation
    "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "CP0000EZ19M086NEST",
    # Labour
    "UNRATE", "PAYEMS", "U6RATE", "AHETPI", "CIVPART",
    # Output
    "GDP", "GDPC1", "INDPRO", "TCU",
    # Demand
    "RSAFS", "PCE", "DSPIC96",
    # Housing
    "HOUST", "PERMIT", "MORTGAGE30US", "CSUSHPISA",
    # Rates / yields
    "DGS10", "DGS2", "DGS30", "DGS5", "DGS3MO",
    "FEDFUNDS", "DFEDTARU", "DFEDTARL",
    "T10Y3M", "T10Y2Y",
    # FX
    "DTWEXBGS", "DTWEXAFEGS", "DTWEXEMEGS",
    "DEXUSEU", "DEXJPUS", "DEXCHUS", "DEXUSUK",
    # Money / credit
    "M1SL", "M2SL", "BUSLOANS", "TOTRESNS",
    # Sentiment / surveys
    "UMCSENT", "USREC",
    # Inflation expectations
    "T5YIE", "T10YIE", "T5YIFR",
    # Commodities
    "DCOILWTICO", "DCOILBRENTEU", "GOLDAMGBD228NLBM",
    # Equities (FRED carries SP500 daily)
    "SP500", "NASDAQCOM",
    # Bonds / spreads
    "BAMLH0A0HYM2", "BAA10Y", "AAA10Y",
    # International
    "DEXUSAL", "DEXKOUS", "DEXBZUS",
    # Misc
    "ICSA", "CCSA", "JTSJOL", "JTSHIL", "PRS85006092", "OPHNFB",
)

assert len(_PHASE_83_CATALOG_IDS) == 64, (
    f"Phase 83 catalog must be exactly 64 IDs; got {len(_PHASE_83_CATALOG_IDS)}"
)


@pytest.fixture(scope="session")
def mock_economic_indicator_catalog() -> list[dict[str, str]]:
    """Return the locked subset of the Phase 83 EconomicIndicator catalog."""
    return [{"id": iid} for iid in _PHASE_83_CATALOG_IDS]


@pytest.fixture(scope="session")
def indicator_synonyms_yaml_path() -> Path:
    return _DATA_ROOT / "indicator_synonyms.yaml"


@pytest.fixture(scope="session")
def asset_universe_yaml_path() -> Path:
    return _DATA_ROOT / "asset_universe.yaml"


@pytest.fixture(scope="session", autouse=True)
def _set_indicator_catalog_env_for_tests():
    """Tell the indicator_linker (production code) to read the catalog from a
    local file path in tests rather than calling out to VM100.

    Production sets VM100_INDICATOR_CATALOG_URL to a URL; tests set
    PHASE92_INDICATOR_CATALOG_FILE to a path. The linker checks the file
    path first.
    """
    catalog_file = _FIXTURES_ROOT / "_test_catalog.yaml"
    if not catalog_file.exists():
        catalog_file.write_text(
            yaml.safe_dump({"indicators": [{"id": i} for i in _PHASE_83_CATALOG_IDS]})
        )
    os.environ["PHASE92_INDICATOR_CATALOG_FILE"] = str(catalog_file)
    yield
    os.environ.pop("PHASE92_INDICATOR_CATALOG_FILE", None)
