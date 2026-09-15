"""Reproducible precision metrics for deduplication and lexical matching.

The evaluator never labels its own data. Humans fill the ``label`` column in
CSV files generated from real examples; this module only applies the production
algorithms and computes the confusion matrix.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .match import jd_keywords
from .normalize import Job


def _bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"0", "1", "false", "true", "no", "yes"}:
        raise ValueError(f"label must be yes/no or 1/0, got {value!r}")
    return normalized in {"1", "true", "yes"}


def classification_metrics(actual: list[bool], predicted: list[bool]) -> dict[str, float | int]:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("actual and predicted must be non-empty and the same length")
    tp = sum(a and p for a, p in zip(actual, predicted))
    fp = sum(not a and p for a, p in zip(actual, predicted))
    fn = sum(a and not p for a, p in zip(actual, predicted))
    tn = len(actual) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "sample_size": len(actual), "true_positive": tp, "false_positive": fp,
        "false_negative": fn, "true_negative": tn,
        "precision": round(precision, 4), "recall": round(recall, 4),
    }


def _job(prefix: str, row: dict[str, str]) -> Job:
    return Job(
        id=prefix, source_repo="evaluation", company=row[f"{prefix}_company"],
        title=row[f"{prefix}_title"], category="", active=1, is_visible=1,
        terms=[], date_posted=0, date_updated=0, url=row[f"{prefix}_url"],
        locations=[], company_url="", sponsorship_simplify="", degrees=[],
    )


def evaluate_dedup(path: str | Path) -> dict[str, float | int]:
    actual: list[bool] = []
    predicted: list[bool] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("label", "").strip():
                continue
            actual.append(_bool(row["label"]))
            predicted.append(_job("left", row).dedup_key == _job("right", row).dedup_key)
    return classification_metrics(actual, predicted)


def _tokens(text: str) -> set[str]:
    # Reuse the production tokenizer/weights rather than inventing an evaluator.
    return set(jd_keywords("", "", text))


def evaluate_matching(path: str | Path, threshold: float = 0.25) -> dict[str, float | int]:
    actual: list[bool] = []
    predicted: list[bool] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("label", "").strip():
                continue
            target = _tokens(" ".join((row["title"], row["category"], row["terms"])))
            profile = _tokens(row["profile_text"])
            score = len(target & profile) / len(target) if target else 0.0
            actual.append(_bool(row["label"]))
            predicted.append(score >= threshold)
    result = classification_metrics(actual, predicted)
    result["threshold"] = threshold
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    dedup = sub.add_parser("dedup")
    dedup.add_argument("labels")
    matching = sub.add_parser("matching")
    matching.add_argument("labels")
    matching.add_argument("--threshold", type=float, default=0.25)
    args = parser.parse_args()
    result = (evaluate_dedup(args.labels) if args.kind == "dedup"
              else evaluate_matching(args.labels, args.threshold))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
