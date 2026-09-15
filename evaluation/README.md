# Labeled precision evaluation

Copy the example CSVs, replace the examples with at least 50 real cases, and
have a person label each row before running the evaluator:

```bash
jobengine evaluate dedup evaluation/dedup-labels.csv
jobengine evaluate matching evaluation/matching-labels.csv --threshold 0.25
```

The report includes sample size, TP/FP/FN/TN, precision, and recall. Blank
labels are ignored so labeling can be resumed. The evaluator reuses production
normalization and tokenization; it does not quietly substitute an easier model.

Do not tune the threshold and report precision on the same rows. Use one sample
to choose the threshold and a separate holdout sample for the final metric.
