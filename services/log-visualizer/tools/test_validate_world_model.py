#!/usr/bin/env python3
import copy
import unittest

from tools.validate_world_model import validate
from tools.reconstruct_world_model import apply_entity_links


def evidence():
    return [{"type": "artifact", "path": "REPORT.md", "itemId": None, "note": "fixture"}]


def base_model():
    return {
        "schemaVersion": 2,
        "runId": "test-run",
        "narrative": "A test run completed.",
        "current_best": "Score 1.0.",
        "crux": "The fixture has limited scope.",
        "cruxEvidence": [{"type": "finding", "id": "F1"}],
        "hypotheses": [{
            "id": "H1", "statement": "The method helps.", "status": "supported",
            "evidence": evidence(),
        }],
        "experiments": [{"id": "E1", "agent": "experiment_runner", "status": "done"}],
        "findings": [{
            "id": "F1", "text": "The method improved the score.", "kind": "result",
            "evidence": evidence(),
            "links": [
                {"relation": "supports", "target": "H1", "basis": "explicit", "rationale": "The measured direction matches H1."},
                {"relation": "produced_by", "target": "E1", "basis": "explicit", "rationale": "E1 generated the measured output."},
            ],
        }],
        "decisions": [{
            "id": "D1", "phase": "planning", "question": "Which method should be used?",
            "options": [{"text": "Use method A", "status": "chosen", "source": "inferred"}],
            "chosen": "Use method A", "statedRationale": "It matches the hypothesis.",
            "inferredRationale": None, "by": "agent", "importance": "high",
            "shouldEngage": False, "shouldEngageReason": "routine_no", "evidence": evidence(),
            "links": [{"relation": "caused", "target": "I1", "basis": "inferred", "rationale": "The choice exposed the failure."}],
        }],
        "incidents": [{
            "id": "I1", "kind": "recovered", "detail": "The first attempt failed.",
            "evidence": evidence(),
            "links": [{"relation": "recovered_by", "target": "E1", "basis": "explicit", "rationale": "E1 was rerun successfully."}],
        }],
    }


class EntityLinkValidationTests(unittest.TestCase):
    def validate(self, model):
        return validate(model, min_decisions=1, max_decisions=12)

    def test_valid_links_pass(self):
        report = self.validate(base_model())
        self.assertEqual([], [error for error in report.errors if error["code"].startswith("link_")])

    def test_dangling_target_fails(self):
        model = base_model()
        model["findings"][0]["links"][0]["target"] = "H99"
        report = self.validate(model)
        self.assertIn("link_target", {error["code"] for error in report.errors})

    def test_incompatible_direction_fails(self):
        model = base_model()
        model["hypotheses"][0]["links"] = [{
            "relation": "supports", "target": "F1", "basis": "inferred",
            "rationale": "Reverse links are not canonical.",
        }]
        report = self.validate(model)
        self.assertIn("link_type", {error["code"] for error in report.errors})

    def test_duplicate_link_fails(self):
        model = base_model()
        model["findings"][0]["links"].append(copy.deepcopy(model["findings"][0]["links"][0]))
        report = self.validate(model)
        self.assertIn("link_duplicate", {error["code"] for error in report.errors})

    def test_fanout_links_attach_after_ids_are_final(self):
        model = base_model()
        model["findings"][0].pop("links")
        apply_entity_links(model, [{
            "source": "F1", "relation": "supports", "target": "H1",
            "basis": "explicit", "rationale": "The result matches H1.",
        }])
        self.assertEqual("H1", model["findings"][0]["links"][0]["target"])


if __name__ == "__main__":
    unittest.main()
