import csv

import pytest

from jobengine.evaluation import classification_metrics, evaluate_dedup, evaluate_matching


def _write(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_classification_metrics():
    result = classification_metrics([True, True, False, False], [True, False, True, False])
    assert result == {"sample_size": 4, "true_positive": 1, "false_positive": 1,
                      "false_negative": 1, "true_negative": 1,
                      "precision": 0.5, "recall": 0.5}


def test_dedup_precision_uses_production_key(tmp_path):
    path = tmp_path / "dedup.csv"
    fields = [f"{side}_{name}" for side in ("left", "right")
              for name in ("company", "title", "url")] + ["label"]
    _write(path, fields, [{
        "left_company": "Google LLC", "left_title": "Software Engineer",
        "left_url": "https://jobs.test/1?utm_source=a", "right_company": "Google",
        "right_title": "Software Engineer", "right_url": "https://jobs.test/1#top",
        "label": "yes",
    }])
    assert evaluate_dedup(path)["precision"] == 1.0


def test_matching_precision(tmp_path):
    path = tmp_path / "matching.csv"
    fields = ["title", "category", "terms", "profile_text", "label"]
    _write(path, fields, [
        {"title": "Java Engineer", "category": "newgrad", "terms": "spring postgres",
         "profile_text": "Java Spring PostgreSQL", "label": "yes"},
        {"title": "Computer Vision Scientist", "category": "newgrad", "terms": "pytorch",
         "profile_text": "Java Spring PostgreSQL", "label": "no"},
    ])
    result = evaluate_matching(path, threshold=0.25)
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_empty_labels_are_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    _write(path, ["title", "category", "terms", "profile_text", "label"], [])
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_matching(path)
