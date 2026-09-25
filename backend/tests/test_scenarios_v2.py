from pathlib import Path

from backend.app.scenarios.harness import ScenarioBundle, compare_invariants


def test_all_acceptance_scenarios_are_discoverable():
    root = Path(__file__).resolve().parents[2] / "scenarios"
    ids = {path.name.split("_")[0] for path in root.iterdir() if path.is_dir()}
    assert ids == {f"S{index:02d}" for index in range(1, 26)}
    for path in root.iterdir():
        if path.is_dir():
            bundle = ScenarioBundle.load(path)
            assert bundle.expected


def test_expected_is_subset_not_snapshot():
    assert compare_invariants({"ncr": {"open": True, "id": "x"}, "extra": 1}, {"ncr": {"open": True}}) == []


def test_delivery_order_is_preserved(tmp_path):
    scenario = tmp_path / "S00"; scenario.mkdir()
    (scenario / "events.jsonl").write_text('{"event_id":"second"}\n{"event_id":"first"}\n', encoding="utf-8")
    (scenario / "expected.json").write_text('{"ok":true}', encoding="utf-8")
    assert [row["event_id"] for row in ScenarioBundle.load(scenario).events] == ["second", "first"]
