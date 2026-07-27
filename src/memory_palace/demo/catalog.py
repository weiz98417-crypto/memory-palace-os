from pathlib import Path

import yaml

from .models import ScenarioDefinition


class ScenarioCatalog:
    """Loads and validates the versioned scenario definitions."""

    def __init__(self, scenario_dir: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self._scenario_dir = scenario_dir or project_root / "scripts" / "seed_data" / "demo"
        self._scenarios = self._load()

    def list(self) -> list[ScenarioDefinition]:
        return list(self._scenarios.values())

    def get(self, scenario_id: str) -> ScenarioDefinition:
        try:
            return self._scenarios[scenario_id]
        except KeyError as exc:
            raise KeyError(f"Unknown demo scenario: {scenario_id}") from exc

    def _load(self) -> dict[str, ScenarioDefinition]:
        scenarios: dict[str, ScenarioDefinition] = {}
        for path in sorted(self._scenario_dir.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as stream:
                scenario = ScenarioDefinition.model_validate(yaml.safe_load(stream))
            if scenario.id in scenarios:
                raise ValueError(f"Duplicate demo scenario id: {scenario.id}")
            scenarios[scenario.id] = scenario
        if not scenarios:
            raise RuntimeError(f"No demo scenarios found in {self._scenario_dir}")
        return scenarios
