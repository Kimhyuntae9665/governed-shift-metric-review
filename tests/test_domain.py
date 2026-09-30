"""Evaluator-only frozen gold and independent domain boundary regressions."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fractions import Fraction

from metric_review.domain import analyze, load_snapshot, ClarificationRequired

ROOT = Path(__file__).resolve().parents[1]
GOLD = json.loads((ROOT / "evaluations/gold.json").read_text())


def reseal(envelope):
    original = {k: v for k, v in envelope.items() if k not in ("source_sha256", "canonical_sha256")}
    body = json.dumps(original, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    envelope["canonical_sha256"] = hashlib.sha256(body).hexdigest()
    envelope["source_sha256"] = hashlib.sha256(body).hexdigest()


class DomainFixture(unittest.TestCase):
    def setUp(self):
        self.snapshot = load_snapshot(ROOT / "data")
        self.request = dict(GOLD["default_request"], dataset_id="baseline")
        self.request["authorized_sites"] = self.request.pop("site_ids")

    def run_request(self, **overrides):
        request = dict(self.request, **overrides)
        return analyze(self.snapshot["sources"], self.snapshot["manifest"], self.snapshot["catalog"], **request)

    def metrics(self, result):
        return {name: row["exact"] for name, row in result["combined"]["metrics"].items()}


class FrozenGoldTests(DomainFixture):
    pass


def frozen_case(case):
    def check(self):
        request = {k: case[k] for k in ("as_of_cutoff", "business_date") if k in case}
        request["dataset_id"] = case.get("dataset_id", "baseline")
        request.update(case.get("query", {}))
        if case["status"] == "clarification_required":
            with self.assertRaisesRegex(ClarificationRequired, case["reason"]):
                self.run_request(**request)
            return
        result = self.run_request(**request)
        self.assertEqual(result["status"], case["status"])
        if "metrics" in case:
            self.assertEqual(self.metrics(result), case["metrics"])
        for field in ("accepted_pairs", "expected_pairs"):
            if field in case:
                self.assertEqual(result["coverage"][field], case[field])
        reasons = [row["reason"] for row in result["quarantine"]]
        flags = result["combined"]["flags"] + [r["reason"] for r in result["replays"]]
        if "reason" in case:
            self.assertIn(case["reason"], reasons + flags)
        if "flag" in case:
            self.assertIn(case["flag"], flags)
        shift_oee = {row["key"]["site_id"] + "/" + row["key"]["shift_id"]: row["metrics"]["oee"]["exact"]
                     for row in result["per_shift"]}
        for field in ("shift_oee", "accepted_shift_oee"):
            if field in case:
                for key, exact in case[field].items():
                    self.assertEqual(shift_oee[key], exact)
        if "percentages" in case:
            for name, value in case["percentages"].items():
                self.assertEqual(Fraction(result["combined"]["metrics"][name]["percentage_exact"]), Fraction(value))
        if "naive_average" in case:
            self.assertEqual(result["combined"]["naive_average_oee"]["exact"], case["naive_average"])
            self.assertEqual(result["combined"]["naive_average_gap_percentage_points"]["exact"],
                             case["average_gap_percentage_points"])
        if "oee_percent_four_places" in case:
            self.assertEqual(result["combined"]["metrics"]["oee"]["percentage_4dp"], case["oee_percent_four_places"])
        if "forbidden_text" in case:
            self.assertNotIn(case["forbidden_text"], json.dumps(result))
    return check


for case in GOLD["cases"]:
    setattr(FrozenGoldTests, "test_frozen_" + case["id"], frozen_case(case))


class BoundaryTests(DomainFixture):
    def test_runtime_loader_never_opens_evaluator_gold(self):
        opened = []
        original = Path.read_bytes
        def guarded(path):
            opened.append(str(path))
            self.assertNotIn("evaluations", path.parts)
            return original(path)
        with patch.object(Path, "read_bytes", guarded):
            snapshot = load_snapshot(ROOT / "data")
        self.assertEqual(len(opened), 5)
        self.assertEqual(set(snapshot["sources"]), {"mes_counts", "shift_time"})

    def test_changed_frozen_source_is_rejected_before_any_arithmetic(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            for path in (ROOT / "data").glob("*.json"):
                shutil.copyfile(path, target / path.name)
            path = target / "mes_counts.json"
            path.write_text(path.read_text().replace('"good_count": 81', '"good_count": 1', 1))
            with self.assertRaisesRegex(ValueError, "frozen_source_hash_mismatch"):
                load_snapshot(target)

    def test_changed_in_memory_snapshot_is_rejected(self):
        self.snapshot["sources"]["mes_counts"]["records"][0]["good_count"] = 1
        with self.assertRaisesRegex(ValueError, "source_snapshot_changed"):
            self.run_request()

    def test_explicit_cutoff_date_and_approved_selector_required(self):
        for cutoff in (None, "", "2026-10-02T00:30:00", "next shift", 42):
            with self.assertRaises(ValueError):
                self.run_request(as_of_cutoff=cutoff)
        for day in ("2026-10-02", "today", "2026-02-30"):
            with self.assertRaises(ValueError):
                self.run_request(business_date=day)
        for metric in ("uptime", "SELECT * FROM metrics", "", None):
            with self.assertRaises(ClarificationRequired):
                self.run_request(metric_id=metric)
        for dataset in ("baseline; DROP TABLE rows", "unknown"):
            with self.assertRaises(ValueError):
                self.run_request(dataset_id=dataset)
        with self.assertRaises(TypeError):
            self.run_request(sql="SELECT * FROM rows")

    def test_no_authorized_scope_stops_before_revision_join(self):
        with patch("metric_review.domain._resolve") as resolver:
            for sites in ([], ["PLANT-SECRET"], "PLANT-A"):
                with self.assertRaises(PermissionError):
                    self.run_request(authorized_sites=sites)
        resolver.assert_not_called()

    def test_unauthorized_values_and_invalid_metadata_never_enter_receipt(self):
        source = self.snapshot["sources"]["mes_counts"]
        row = next(row for row in source["records"] if row["dataset_id"] == "unauthorized_site" and row["site_id"] == "PLANT-SECRET")
        row.update(record_id="SECRET-EXISTENCE-987", issued_at="bad-secret-cutoff", revision=-1,
                   total_count=123456789, good_count=123456789)
        reseal(source)
        result = self.run_request(dataset_id="unauthorized_site")
        text = json.dumps(result)
        for forbidden in ("PLANT-SECRET", "SECRET-EXISTENCE-987", "123456789", "bad-secret-cutoff"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(result["coverage"]["accepted_pairs"], 2)
        self.assertEqual(result["quarantine"], [])

    def test_future_conflicting_revision_does_not_taint_historical_cutoff(self):
        source = self.snapshot["sources"]["mes_counts"]
        row = copy.deepcopy(next(row for row in source["records"] if row["dataset_id"] == "baseline" and row["record_id"] == "COUNT-A"))
        row.update(good_count=82, issued_at="2026-10-02T01:00:00+09:00")
        source["records"].append(row)
        reseal(source)
        before = self.run_request()
        self.assertEqual(self.metrics(before)["oee"], "147/160")
        self.assertNotIn("conflicting_revision", [row["reason"] for row in before["quarantine"]])
        after = self.run_request(as_of_cutoff="2026-10-02T01:30:00+09:00")
        self.assertEqual(self.metrics(after)["availability"], "15/16")
        self.assertIsNone(self.metrics(after)["oee"])
        self.assertFalse(after["coverage"]["complete_pairs"])

    def test_timezone_equivalent_cutoff_and_revision_not_string_order(self):
        local = self.run_request()
        utc = self.run_request(as_of_cutoff="2026-10-01T15:30:00Z")
        self.assertEqual(self.metrics(local), self.metrics(utc))
        first = self.run_request(dataset_id="correction_review", as_of_cutoff="2026-10-01T14:30:00Z")
        self.assertEqual(self.metrics(first)["oee"], "11/12")
        self.assertEqual({row["revision"] for row in first["accepted"]["counts"] if row["record_id"] == "COUNT-A"}, {1})

    def test_explicit_subset_updates_expected_manifest_scope(self):
        result = self.run_request(shift_ids=["A"])
        self.assertEqual(result["coverage"]["expected_pairs"], 1)
        self.assertEqual(self.metrics(result)["oee"], "27/40")
        self.assertEqual(result["combined"]["naive_average_gap_percentage_points"]["exact"], "0")
        with self.assertRaises(ClarificationRequired):
            self.run_request(shift_ids=["last shift"])

    def test_minute_conversion_is_traceable_and_exact(self):
        result = self.run_request()
        rows = [row for row in result["conversions"] if row["record_id"] == "TIME-B"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["source_unit"] == "min" and row["multiplier_exact"] == "60" for row in rows))
        self.assertTrue(all(row["input_exact"] == "180" and row["output_exact"] == "10800" for row in rows))
        self.assertTrue(all(len(row["source_sha256"]) == 64 for rows in result["accepted"].values() for row in rows))

    def test_zero_denominator_nulls_never_fall_back_to_zero_or_hundred(self):
        result = self.run_request(dataset_id="zero_denominator")
        self.assertTrue(all(row["exact"] is None and row["undefined_reason"] == "zero_denominator"
                            for row in result["combined"]["metrics"].values()))
        self.assertIsNone(result["combined"]["naive_average_oee"])

    def test_replay_cannot_inflate_totals_or_expected_coverage(self):
        result = self.run_request(dataset_id="duplicate_counts")
        self.assertEqual(len(result["accepted"]["counts"]), 1)
        self.assertEqual(result["accepted"]["counts"][0]["values"]["total_count"], "90")
        self.assertEqual(result["coverage"]["expected_pairs"], 1)
        self.assertEqual(len(result["replays"]), 1)

    def test_incomplete_scope_does_not_fall_back_to_b_only_one_hundred(self):
        result = self.run_request(dataset_id="conflicting_revision")
        self.assertEqual(result["coverage"]["expected_pairs"], 2)
        self.assertEqual(result["coverage"]["accepted_pairs"], 1)
        self.assertIsNone(self.metrics(result)["oee"])
        self.assertEqual(result["per_shift"][1]["metrics"]["oee"]["exact"], "1")

    def test_integer_only_source_values_reject_bool_float_and_negative(self):
        for bad in (True, 90.0, -1, "90"):
            snapshot = load_snapshot(ROOT / "data")
            row = next(row for row in snapshot["sources"]["mes_counts"]["records"] if row["dataset_id"] == "baseline" and row["record_id"] == "COUNT-A")
            row["total_count"] = bad
            reseal(snapshot["sources"]["mes_counts"])
            result = analyze(snapshot["sources"], snapshot["manifest"], snapshot["catalog"], **self.request)
            self.assertIsNone(self.metrics(result)["oee"])
            self.assertIn("invalid_count", [row["reason"] for row in result["quarantine"]])

    def test_unapproved_catalog_or_edited_definition_cannot_compute(self):
        for edit in ("approval", "definition", "cycle"):
            catalog = copy.deepcopy(self.snapshot["catalog"])
            if edit == "approval":
                catalog["approval"]["status"] = "draft"
            elif edit == "definition":
                catalog["metrics"]["oee"]["denominator"] = "arbitrary SQL"
            else:
                catalog["cycles"][0]["ideal_cycle_seconds"] = True
            with self.assertRaises(ValueError):
                analyze(self.snapshot["sources"], self.snapshot["manifest"], catalog, **self.request)

    def test_overnight_uses_export_date_without_clock_inference(self):
        result = self.run_request(dataset_id="overnight")
        self.assertEqual(result["per_shift"][0]["key"]["business_date"], "2026-10-01")
        self.assertEqual(result["per_shift"][0]["key"]["shift_id"], "NIGHT")
        with self.assertRaises(ValueError):
            self.run_request(dataset_id="overnight", business_date="2026-10-02")


    def test_catalog_cycle_approval_requires_boolean_not_truthiness(self):
        for invalid in ("false", "true", 1, 0, None, [], {}):
            catalog = copy.deepcopy(self.snapshot["catalog"])
            catalog["cycles"][0]["approved"] = invalid
            with self.subTest(approval=invalid), self.assertRaisesRegex(ValueError, "invalid_cycle_approval"):
                analyze(self.snapshot["sources"], self.snapshot["manifest"], catalog, **self.request)

    def test_explicit_false_cycle_approval_cannot_enable_cycle(self):
        catalog = copy.deepcopy(self.snapshot["catalog"])
        catalog["cycles"][0]["approved"] = False
        result = analyze(self.snapshot["sources"], self.snapshot["manifest"], catalog, **self.request)
        self.assertIsNone(self.metrics(result)["oee"])
        self.assertEqual(result["accepted"]["counts"], [])
        self.assertIn("unsupported_ideal_cycle", [row["reason"] for row in result["quarantine"]])

    def latest_outside_expected(self, field, invalid_value):
        source = self.snapshot["sources"]["mes_counts"]
        latest = copy.deepcopy(next(row for row in source["records"] if row["dataset_id"] == "correction_review" and row["record_id"] == "COUNT-A" and row["revision"] == 2))
        latest[field] = invalid_value
        original = next(row for row in source["records"] if row["dataset_id"] == "correction_review" and row["record_id"] == "COUNT-A" and row["revision"] == 2)
        original.update(latest)
        reseal(source)
        historical = self.run_request(dataset_id="correction_review", as_of_cutoff="2026-10-01T23:30:00+09:00")
        self.assertEqual(self.metrics(historical)["oee"], "11/12")
        self.assertEqual([row["revision"] for row in historical["accepted"]["counts"] if row["record_id"] == "COUNT-A"], [1])
        current = self.run_request(dataset_id="correction_review")
        self.assertIsNone(self.metrics(current)["oee"])
        self.assertEqual(self.metrics(current)["availability"], "15/16")
        self.assertEqual(current["coverage"]["accepted_pairs"], 1)
        self.assertEqual([row for row in current["accepted"]["counts"] if row["record_id"] == "COUNT-A"], [])
        self.assertIn("unexpected_scope_key", [row["reason"] for row in current["quarantine"]])
        self.assertIn("superseded_revision", [row["reason"] for row in current["superseded"] if row["record_id"] == "COUNT-A"])

    def test_latest_wrong_product_has_no_older_expected_key_fallback(self):
        self.latest_outside_expected("product_id", "P-WRONG")

    def test_latest_wrong_cycle_has_no_older_expected_key_fallback(self):
        self.latest_outside_expected("cycle_version", "IC-WRONG")

    def test_latest_malformed_join_key_has_no_older_revision_fallback(self):
        source = self.snapshot["sources"]["mes_counts"]
        row = next(row for row in source["records"] if row["dataset_id"] == "correction_review" and row["record_id"] == "COUNT-A" and row["revision"] == 2)
        row["product_id"] = None
        reseal(source)
        current = self.run_request(dataset_id="correction_review")
        self.assertIsNone(self.metrics(current)["oee"])
        self.assertEqual([row for row in current["accepted"]["counts"] if row["record_id"] == "COUNT-A"], [])
        self.assertIn("invalid_join_key", [row["reason"] for row in current["quarantine"]])


if __name__ == "__main__":
    unittest.main()
