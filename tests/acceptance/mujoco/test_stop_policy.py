"""Freeze stop/null semantics at the backend acceptance boundary."""
import json

from tests.acceptance import load_suite
from tests.acceptance.mujoco import executor as mod


def test_historical_passing_case_failure_stops_and_preserves_denominator(tmp_path, monkeypatch):
    suite = load_suite()
    history = tmp_path / 'old.json'
    history.write_text(json.dumps({'results': [{'case': c.case_id, 'physics_passed': True, 'target_min': 1.}
                                               for c in suite.cases]}))
    calls = []
    def fail(executor, suite, case, sink):
        calls.append(case.case_id)
        executor.mapping = {}
        return {'case': case.case_id, 'physics_passed': False, 'target_min': 0.}
    monkeypatch.setattr(mod, 'run_case', fail)
    monkeypatch.setattr(mod.MujocoPressExecutor, 'step_performance', lambda _: {})
    report = mod.execute_suite(tmp_path / 'new', historical_results=history, stop_on_regression=True)
    assert calls == [suite.cases[0].case_id]
    assert report['summary']['planned'] == 26
    assert report['summary']['completed'] == 1
    assert report['historical_regressions'] == [suite.cases[0].case_id]
    assert all(r['physics_passed'] is None for r in report['results'][1:])
    assert all(r['status'] == 'not_run' for r in report['results'][1:])
