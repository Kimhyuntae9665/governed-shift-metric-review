"""Exact approved shift metrics. No model, SQL, network, or evaluator access."""
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
from pathlib import Path

KEYS = ("site_id", "line_id", "business_date", "shift_id", "product_id", "cycle_version")
METRICS = ("availability", "performance", "quality", "oee")
MAX_EXPORT_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 1000
DEFINITIONS = {
    "availability": {"numerator": "run_time_s", "denominator": "planned_time_s"},
    "performance": {"numerator": "total_count * ideal_cycle_seconds", "denominator": "run_time_s"},
    "quality": {"numerator": "good_count", "denominator": "total_count"},
    "oee": {"numerator": "good_count * ideal_cycle_seconds", "denominator": "planned_time_s"},
}


class ClarificationRequired(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("explicit_timezone_cutoff_required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("explicit_timezone_cutoff_required") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("explicit_timezone_cutoff_required")
    return result


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("explicit_business_date_required")
    date.fromisoformat(value)
    return value


def _ident(value):
    return isinstance(value, str) and 1 <= len(value) <= 100 and re.fullmatch(r"[A-Za-z0-9_.-]+", value) is not None


def _integer(value):
    return type(value) is int and 0 <= value <= 10**18


def _key(row):
    if any(not isinstance(row.get(field), str) or not 1 <= len(row[field]) <= 100 for field in KEYS):
        raise ValueError("invalid_join_key")
    _day(row["business_date"])
    return tuple(row[field] for field in KEYS)


def _key_dict(key):
    return dict(zip(KEYS, key))


def load_snapshot(data_dir):
    """Read an immutable runtime snapshot; evaluator gold is never opened."""
    root = Path(data_dir)
    freeze_path = root / "freeze_manifest.json"
    if freeze_path.stat().st_size > MAX_EXPORT_BYTES:
        raise ValueError("freeze_manifest_too_large")
    freeze = json.loads(freeze_path.read_bytes())
    hashes = {}
    objects = {}
    for name in ("mes_counts.json", "shift_time.json", "scope_manifest.json", "metric_catalog.json"):
        path = root / name
        if path.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("runtime_source_too_large")
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if freeze.get("files", {}).get("data/" + name) != digest:
            raise ValueError("frozen_source_hash_mismatch")
        hashes[name] = digest
        objects[name] = json.loads(body)
    sources = {}
    for name, key in (("mes_counts.json", "mes_counts"), ("shift_time.json", "shift_time")):
        value = objects[name]
        if not isinstance(value, dict):
            raise ValueError("invalid_source_envelope")
        sources[key] = dict(value, source_sha256=hashes[name], canonical_sha256=_hash(value))
    return {"sources": sources, "manifest": objects["scope_manifest.json"],
            "catalog": objects["metric_catalog.json"], "snapshot_hash": _hash(hashes)}


def _catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get("approval", {}).get("status") != "approved":
        raise ValueError("approved_catalog_required")
    if catalog.get("metrics") != DEFINITIONS or catalog.get("join_keys") != list(KEYS):
        raise ValueError("unsupported_metric_definition")
    if catalog.get("units") != {"count": "each", "time_conversions_to_s": {"s": 1, "min": 60}}:
        raise ValueError("unsupported_unit_catalog")
    if not _ident(catalog.get("rule_version")):
        raise ValueError("invalid_rule_version")
    cycles = {}
    for row in catalog.get("cycles", []):
        if not isinstance(row, dict) or type(row.get("approved")) is not bool:
            raise ValueError("invalid_cycle_approval")
        if row["approved"] is not True:
            continue
        key = (row.get("product_id"), row.get("cycle_version"))
        value = row.get("ideal_cycle_seconds")
        if not all(_ident(v) for v in key) or not _integer(value) or value == 0 or key in cycles:
            raise ValueError("invalid_approved_cycle")
        cycles[key] = value
    return cycles


def _metric(numerator=None, denominator=None, reason=None):
    if reason:
        exact = None
    elif numerator is None or denominator is None:
        reason = "unsupported_inputs"
        exact = None
    elif denominator == 0:
        reason = "zero_denominator"
        exact = None
    else:
        exact = Fraction(numerator, denominator)
    return {"exact": str(exact) if exact is not None else None,
            "percentage_exact": str(exact * 100) if exact is not None else None,
            "percentage_4dp": _decimal(exact * 100) if exact is not None else None,
            "numerator_exact": str(numerator) if numerator is not None else None,
            "denominator_exact": str(denominator) if denominator is not None else None,
            "undefined_reason": reason}


def _decimal(value):
    with localcontext() as context:
        context.prec = 100
        return str((Decimal(value.numerator) / Decimal(value.denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_EVEN))


def _info(source_type, row, reason):
    return {"source_type": source_type, "record_id": row.get("record_id"),
            "revision": row.get("revision"), "key": {k: row.get(k) for k in KEYS}, "reason": reason}


def _source(source_type, envelope):
    if not isinstance(envelope, dict) or not isinstance(envelope.get("records"), list):
        raise ValueError("invalid_source_envelope")
    if len(envelope["records"]) > MAX_RECORDS:
        raise ValueError("record_budget_exceeded")
    schema = "mes-count-v1" if source_type == "counts" else "shift-time-v1"
    if envelope.get("schema_version") != schema:
        raise ValueError("unsupported_source_schema")
    receipt = envelope.get("receipt")
    if not isinstance(receipt, dict) or not _ident(receipt.get("id")) or type(receipt.get("revision")) is not int or receipt["revision"] < 1:
        raise ValueError("invalid_receipt")
    _stamp(receipt.get("received_at"))
    digest = envelope.get("source_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("server_source_hash_required")
    original = {k: v for k, v in envelope.items() if k not in ("source_sha256", "canonical_sha256")}
    if envelope.get("canonical_sha256") != _hash(original):
        raise ValueError("source_snapshot_changed")
    return {"receipt_id": receipt["id"], "revision": receipt["revision"],
            "source_sha256": digest, "schema_version": schema,
            "received_at": receipt["received_at"],
            "cutoff_semantics": "historical_source_record_time_not_receiver_knowledge"}


def _resolve(source_type, envelope, authorized_sites, dataset_id, business_date,
             shifts, expected, cutoff, result):
    selected = defaultdict(list)
    poisoned = set()
    for row in envelope["records"]:
        # Authorization precedes identity resolution. Scope keys are checked
        # after the latest eligible revision, preventing an older-key fallback.
        if not isinstance(row, dict) or row.get("site_id") not in authorized_sites:
            continue
        if row.get("dataset_id") != dataset_id:
            continue
        try:
            issued = _stamp(row.get("issued_at"))
            if issued > cutoff:
                result["superseded"].append(_info(source_type, row, "revision_after_cutoff"))
                continue
            if not _ident(row.get("record_id")) or type(row.get("revision")) is not int or row["revision"] < 1:
                raise ValueError("invalid_record_identity")
        except ValueError as error:
            result["quarantine"].append(_info(source_type, row, str(error)))
            if _ident(row.get("record_id")):
                poisoned.add(row["record_id"])
            continue
        selected[row["record_id"]].append(row)
    resolved = []
    for record_id, rows in selected.items():
        if record_id in poisoned:
            continue
        by_revision = defaultdict(list)
        for row in rows:
            by_revision[row["revision"]].append(row)
        conflict = False
        unique = []
        for revision, copies in by_revision.items():
            fingerprints = {_hash(row) for row in copies}
            if len(fingerprints) != 1:
                conflict = True
                result["quarantine"].append(_info(source_type, copies[0], "conflicting_revision"))
            else:
                unique.append(copies[0])
                for replay in copies[1:]:
                    result["replays"].append(_info(source_type, replay, "duplicate_replay_skipped"))
        if conflict:
            continue
        latest = max(unique, key=lambda row: row["revision"])
        resolved.append(latest)
        for row in unique:
            if row is not latest:
                result["superseded"].append(_info(source_type, row, "superseded_revision"))
    joined = defaultdict(list)
    for row in resolved:
        try:
            key = _key(row)
            if key not in expected:
                raise ValueError("unexpected_scope_key")
        except ValueError as error:
            result["quarantine"].append(_info(source_type, row, str(error)))
            continue
        joined[key].append(row)
    output = {}
    for key, rows in joined.items():
        if len(rows) != 1:
            result["quarantine"].extend(_info(source_type, row, "ambiguous_join") for row in rows)
        else:
            output[key] = rows[0]
    return output


def _normalize(source_type, row, envelope, cycles, result):
    key = _key(row)
    cycle = cycles.get((row["product_id"], row["cycle_version"]))
    reason = None
    if cycle is None:
        reason = "unsupported_ideal_cycle"
    elif row.get("timezone") != "Asia/Seoul":
        reason = "unsupported_business_timezone"
    elif source_type == "counts":
        if row.get("counts_kind") != "delta":
            reason = "unsupported_counts_kind"
        elif row.get("count_unit") != "each":
            reason = "unsupported_count_unit"
        elif not _integer(row.get("total_count")) or (row.get("good_count") is not None and not _integer(row["good_count"])):
            reason = "invalid_count"
        elif row.get("good_count") is not None and row["good_count"] > row["total_count"]:
            reason = "good_exceeds_total"
    else:
        if row.get("business_date_policy") != "explicit":
            reason = "explicit_business_date_required"
        elif row.get("time_unit") not in ("s", "min"):
            reason = "unsupported_time_unit"
        elif not _integer(row.get("planned_time")) or not _integer(row.get("run_time")):
            reason = "invalid_time_value"
    if reason:
        result["quarantine"].append(_info(source_type, row, reason))
        return None
    output = {"key": _key_dict(key), "record_id": row["record_id"], "revision": row["revision"],
              "issued_at": row["issued_at"], "receipt_id": envelope["receipt"]["id"],
              "source_sha256": envelope["source_sha256"], "record_sha256": _hash(row),
              "ideal_cycle_seconds": str(cycle)}
    if source_type == "counts":
        output["values"] = {"total_count": str(row["total_count"]),
                            "good_count": str(row["good_count"]) if row["good_count"] is not None else None}
    else:
        multiplier = 1 if row["time_unit"] == "s" else 60
        output["values"] = {"planned_time_s": str(row["planned_time"] * multiplier),
                            "run_time_s": str(row["run_time"] * multiplier)}
        for field in ("planned_time", "run_time"):
            result["conversions"].append({"record_id": row["record_id"], "revision": row["revision"],
                "receipt_id": envelope["receipt"]["id"], "source_unit": row["time_unit"],
                "target_unit": "s", "multiplier_exact": str(multiplier), "field": field,
                "input_exact": str(row[field]), "output_exact": str(row[field] * multiplier)})
    return output


def _shift(count, shift_time):
    c = count["values"] if count else None
    t = shift_time["values"] if shift_time else None
    total = int(c["total_count"]) if c else None
    good = int(c["good_count"]) if c and c["good_count"] is not None else None
    cycle = int((count or shift_time)["ideal_cycle_seconds"]) if count or shift_time else None
    planned = int(t["planned_time_s"]) if t else None
    run = int(t["run_time_s"]) if t else None
    metrics = {"availability": _metric(run, planned, None if t else "missing_time"),
               "performance": _metric(total * cycle if total is not None else None, run,
                                       None if c and t else "missing_count_or_time"),
               "quality": _metric(good, total, None if good is not None else "missing_good"),
               "oee": _metric(good * cycle if good is not None else None, planned,
                             None if good is not None and t else "missing_good_or_time")}
    flags = []
    for name in ("availability", "performance"):
        if metrics[name]["exact"] is not None and Fraction(metrics[name]["exact"]) > 1:
            flags.append(name + "_above_one")
    return metrics, flags


def analyze(sources, manifest, catalog, *, dataset_id, business_date, as_of_cutoff,
            authorized_sites, metric_id="oee", shift_ids=None):
    if metric_id not in METRICS:
        raise ClarificationRequired("approved_metric_required")
    if not _ident(dataset_id):
        raise ValueError("invalid_dataset_selector")
    _day(business_date)
    cutoff = _stamp(as_of_cutoff)
    if not isinstance(authorized_sites, (list, tuple, set, frozenset)) or not authorized_sites or not all(_ident(v) for v in authorized_sites):
        raise PermissionError("authorized_site_scope_required")
    sites = frozenset(authorized_sites)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "expected-scope-v1":
        raise ValueError("expected_scope_manifest_required")
    candidates = [row for row in manifest.get("datasets", []) if row.get("dataset_id") == dataset_id]
    if len(candidates) != 1:
        raise ValueError("invalid_dataset_selector")
    scope = candidates[0]
    if scope.get("expected_business_date") != business_date or scope.get("timezone") != "Asia/Seoul":
        raise ValueError("business_date_outside_manifest")
    expected = {_key(row) for row in scope.get("expected_keys", []) if row.get("site_id") in sites}
    if not expected:
        raise PermissionError("authorized_site_scope_required")
    shifts = None
    if shift_ids is not None:
        if not isinstance(shift_ids, (list, tuple)) or not shift_ids or not all(_ident(v) for v in shift_ids):
            raise ClarificationRequired("explicit_shift_required")
        shifts = frozenset(shift_ids)
        if not shifts <= {key[3] for key in expected}:
            raise ClarificationRequired("explicit_shift_required")
        expected = {key for key in expected if key[3] in shifts}
    cycles = _catalog(catalog)
    if not isinstance(sources, dict) or set(sources) != {"mes_counts", "shift_time"}:
        raise ValueError("two_export_sources_required")
    receipts = [_source(source_type, sources[name]) for source_type, name in
                (("counts", "mes_counts"), ("times", "shift_time"))]
    result = {"status": None, "rule_version": catalog["rule_version"],
              "snapshot_hash": _hash({"sources": [r["source_sha256"] for r in receipts],
                                     "manifest": manifest, "catalog": catalog}),
              "request": {"dataset_id": dataset_id, "business_date": business_date,
                          "as_of_cutoff": as_of_cutoff, "metric_id": metric_id,
                          "site_ids": sorted({key[0] for key in expected}),
                          "shift_ids": sorted(shifts) if shifts is not None else None},
              "receipts": receipts, "accepted": {"counts": [], "times": []},
              "quarantine": [], "replays": [], "superseded": [], "conversions": [],
              "coverage": {}, "per_shift": [], "combined": {}}
    maps = {}
    for source_type, name in (("counts", "mes_counts"), ("times", "shift_time")):
        envelope = sources[name]
        selected = _resolve(source_type, envelope, sites, dataset_id, business_date,
                            shifts, expected, cutoff, result)
        maps[source_type] = {}
        for key, row in sorted(selected.items()):
            normalized = _normalize(source_type, row, envelope, cycles, result)
            if normalized is not None:
                maps[source_type][key] = normalized
                result["accepted"][source_type].append(normalized)
    counts, times = maps["counts"], maps["times"]
    for key in sorted(expected):
        if key in counts and key not in times:
            result["quarantine"].append({"source_type": "counts", "record_id": counts[key]["record_id"],
                                        "revision": counts[key]["revision"], "key": _key_dict(key), "reason": "unmatched_count"})
        elif key in times and key not in counts:
            result["quarantine"].append({"source_type": "times", "record_id": times[key]["record_id"],
                                        "revision": times[key]["revision"], "key": _key_dict(key), "reason": "unmatched_time"})
        metrics, flags = _shift(counts.get(key), times.get(key))
        result["per_shift"].append({"key": _key_dict(key), "metrics": metrics, "flags": flags})
    complete_counts = expected <= counts.keys()
    complete_times = expected <= times.keys()
    complete_pairs = complete_counts and complete_times
    result["coverage"] = {"expected_keys": [_key_dict(k) for k in sorted(expected)],
                          "expected_pairs": len(expected), "accepted_pairs": len(expected & counts.keys() & times.keys()),
                          "complete_counts": complete_counts, "complete_times": complete_times, "complete_pairs": complete_pairs,
                          "missing_count_keys": [_key_dict(k) for k in sorted(expected - counts.keys())],
                          "missing_time_keys": [_key_dict(k) for k in sorted(expected - times.keys())]}
    mixed = len({(key[4], key[5]) for key in expected}) != 1
    total = sum(int(row["values"]["total_count"]) for row in counts.values())
    all_good = complete_counts and all(row["values"]["good_count"] is not None for row in counts.values())
    good = sum(int(row["values"]["good_count"]) for row in counts.values()) if all_good else None
    planned = sum(int(row["values"]["planned_time_s"]) for row in times.values())
    run = sum(int(row["values"]["run_time_s"]) for row in times.values())
    cycle = cycles.get(next(iter({(key[4], key[5]) for key in expected}))) if not mixed else None
    metrics = {
        "availability": _metric(run, planned, None if complete_times else "incomplete_expected_times"),
        "performance": _metric(total * cycle if cycle else None, run, None if complete_pairs else "incomplete_expected_pairs"),
        "quality": _metric(good, total, None if all_good else "incomplete_or_missing_good_counts"),
        "oee": _metric(good * cycle if good is not None and cycle else None, planned,
                       None if complete_pairs and all_good else "incomplete_or_missing_good_pairs")}
    flags = []
    if mixed:
        metrics = {name: _metric(reason="mixed_product_or_cycle_version") for name in METRICS}
        flags.append("mixed_product_or_cycle_version")
    for name in ("availability", "performance"):
        if metrics[name]["exact"] is not None and Fraction(metrics[name]["exact"]) > 1:
            flags.append(name + "_above_one")
    result["combined"] = {"metrics": metrics, "flags": flags,
                          "naive_average_oee": None, "naive_average_gap_percentage_points": None,
                          "scope": "approved_synthetic_expected_shifts_no_production_benchmark_or_roi"}
    if metrics["oee"]["exact"] is not None and all(row["metrics"]["oee"]["exact"] is not None for row in result["per_shift"]):
        mean = sum((Fraction(row["metrics"]["oee"]["exact"]) for row in result["per_shift"]), Fraction()) / len(expected)
        gap = (Fraction(metrics["oee"]["exact"]) - mean) * 100
        result["combined"]["naive_average_oee"] = _metric(mean, 1)
        result["combined"]["naive_average_gap_percentage_points"] = {"exact": str(gap), "decimal_4dp": _decimal(gap), "unit": "percentage_point"}
    result["status"] = "unsupported" if mixed else "supported" if metrics[metric_id]["exact"] is not None else "partial"
    return result
