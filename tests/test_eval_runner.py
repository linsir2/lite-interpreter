from src.evals.runner import run_seed_evals


def test_run_seed_evals_returns_summary_and_results(tmp_path):
    payload = run_seed_evals(output_dir=tmp_path)

    assert payload["summary"]["total"] >= 8
    assert payload["summary"]["passed"] == payload["summary"]["total"]
    assert "fine_routing_invocations" in payload["summary"]
    assert "routing_stage_counts" in payload["summary"]
    assert "final_mode_counts" in payload["summary"]
    assert (tmp_path / "seed_eval_report.json").exists()
    assert (tmp_path / "seed_eval_report.md").exists()
