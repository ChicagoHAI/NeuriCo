import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_autoresearch import HitlAutoResearchController
from core.scorer import run_scorer
from core.scoring_seal import seal_scoring_files


def test_candidate_scorer_temporarily_unseals_then_reseals_evaluator(tmp_path):
    evaluator = tmp_path / "scoring" / "eval.py"
    evaluator.parent.mkdir()
    evaluator.write_text("print('score')\n", encoding="utf-8")
    controller = object.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.scorer = lambda work_dir: {
        "saw_evaluator": (work_dir / "scoring" / "eval.py").is_file()
    }
    sealed = {"path": seal_scoring_files(tmp_path)}

    result = controller._score_candidate_with_evaluator_exposed(sealed)

    assert result == {"saw_evaluator": True}
    assert not evaluator.exists()
    assert sealed["path"] is not None
    assert (sealed["path"] / "scoring" / "eval.py").is_file()


def test_candidate_scoring_uses_the_real_evaluator_only_during_runtime_scoring(tmp_path):
    evaluator = tmp_path / "scoring" / "eval.py"
    evaluator.parent.mkdir()
    evaluator.write_text(
        """
import json
from pathlib import Path

Path('scoring/results.json').write_text(json.dumps({'metric': 0.91}), encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    controller = object.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.scorer = lambda work_dir: run_scorer(work_dir, timeout=5)
    sealed = {"path": seal_scoring_files(tmp_path)}

    result = controller._score_candidate_with_evaluator_exposed(sealed)

    assert result["success"] is True
    assert result["results"] == {"metric": 0.91}
    assert not evaluator.exists()
    assert sealed["path"] is not None
