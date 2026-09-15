"""Application outcomes and ranking evaluation.

A recommender that is never scored against reality is a decorated guess. This
module closes the loop:

    predicted match -> application -> OA -> interview -> offer/reject
                                                |
                                    ranking evaluation

The functions here are deliberately pure -- they take (score, outcome) pairs
and return metrics -- so the evaluation can be unit-tested with hand-built
cases and so the same code runs over a live database, a CSV of labels, or a
synthetic sanity check. Persistence lives in `store.py`.

Which metric answers which question:

* **NDCG@k** -- is the *ordering* right? The only metric that cares that a
  strong outcome ranked 2nd rather than 20th. This is the headline number
  because the product's core claim is "we rank the right roles first".
* **Precision@k / lift@k** -- of the k roles the user was told to apply to,
  how many actually progressed, and is that better than applying at random?
  Lift is the honest framing: precision of 0.30 sounds mediocre until the
  base rate is 0.08.
* **Brier score + calibration** -- when the system says 0.8, do 80% of those
  progress? A model can rank perfectly and still be badly calibrated, and
  calibration is what makes the number safe to *show* a user.
* **Spearman** -- rank correlation over the whole list, not just the top.

Sample sizes for a single job seeker are small (tens, not thousands). Every
function therefore returns `n` alongside the metric, and `evaluate()` refuses
to report metrics below a minimum sample rather than printing a confident
number computed from four applications.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# The funnel, in order. `index` doubles as the graded relevance label: getting
# to an onsite is a better outcome than getting to an OA, and NDCG needs a
# graded signal rather than a binary one to distinguish those.
FUNNEL: tuple[str, ...] = (
    "applied", "oa", "phone_screen", "interview", "onsite", "offer",
)
TERMINAL: tuple[str, ...] = ("rejected", "ghosted", "withdrawn", "offer")

# Reaching an OA or beyond is the "this application was worth sending" line.
# Chosen deliberately: an application that only ever got a rejection tells you
# almost nothing (companies reject for headcount, timing, and noise), while an
# OA means the resume cleared a real filter.
POSITIVE_FROM = "oa"

_RELEVANCE = {stage: i for i, stage in enumerate(FUNNEL)}


def relevance(stage: str) -> int:
    """Graded relevance for a terminal funnel stage, 0 when it went nowhere."""
    return _RELEVANCE.get(stage, 0)


def is_positive(stage: str) -> bool:
    return relevance(stage) >= _RELEVANCE[POSITIVE_FROM]


def furthest_stage(stages: Iterable[str]) -> str:
    """The deepest funnel stage reached across an application's events.

    Deepest rather than latest, because the event log ends with "rejected"
    for almost every application -- and an application rejected *after an
    onsite* is a success signal for the ranker, not a failure.
    """
    best, best_rank = "applied", -1
    for s in stages:
        r = relevance(s)
        if r > best_rank:
            best, best_rank = s, r
    return best


# --- ranking metrics --------------------------------------------------------

def _dcg(relevances: Sequence[float]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def ndcg_at_k(ranked_relevances: Sequence[float], k: int = 10) -> float:
    """Normalized discounted cumulative gain of an already-ranked list.

    `ranked_relevances` must be ordered by the system's predicted score,
    best first. Returns 0.0 when every outcome is 0 -- with no positive
    outcome there is no ordering to be right about, and returning 1.0 (the
    technically-correct "perfect match to an all-zero ideal") would report
    success for a user who has heard back from nobody.
    """
    top = list(ranked_relevances)[:k]
    ideal = sorted(ranked_relevances, reverse=True)[:k]
    denom = _dcg(ideal)
    return round(_dcg(top) / denom, 4) if denom > 0 else 0.0


def precision_at_k(ranked_labels: Sequence[bool], k: int = 10) -> float:
    top = list(ranked_labels)[:k]
    return round(sum(1 for x in top if x) / len(top), 4) if top else 0.0


def lift_at_k(ranked_labels: Sequence[bool], k: int = 10) -> float:
    """Precision@k divided by the base rate.

    1.0 means the ranking is worth exactly nothing -- the user would have
    done as well applying in random order. This is the number that actually
    justifies the product existing, which is why it is reported even when it
    is unflattering.
    """
    labels = list(ranked_labels)
    base = sum(1 for x in labels if x) / len(labels) if labels else 0.0
    if base == 0:
        return 0.0
    return round(precision_at_k(labels, k) / base, 4)


def brier(predicted: Sequence[float], labels: Sequence[bool]) -> float:
    """Mean squared error between predicted probability and outcome.

    Lower is better; 0.25 is what you get by always guessing 0.5. Scores are
    treated as probabilities here, which they are not by construction -- that
    mismatch is exactly what calibration measures, and the fix is to fit a
    mapping from score to probability once enough outcomes exist.
    """
    pairs = list(zip(predicted, labels))
    if not pairs:
        return 0.0
    return round(sum((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs) / len(pairs), 4)


def calibration_bins(predicted: Sequence[float], labels: Sequence[bool],
                     bins: int = 5) -> list[dict]:
    """Observed positive rate per predicted-score bucket.

    Empty buckets are omitted rather than reported as 0% -- "no applications
    scored 0.8-1.0" and "every 0.8-1.0 application failed" are opposite facts
    and must not render identically.
    """
    buckets: dict[int, list[bool]] = {}
    for p, y in zip(predicted, labels):
        idx = min(bins - 1, max(0, int(p * bins)))
        buckets.setdefault(idx, []).append(bool(y))
    out = []
    for idx in sorted(buckets):
        ys = buckets[idx]
        out.append({
            "bin": f"{idx / bins:.1f}-{(idx + 1) / bins:.1f}",
            "n": len(ys),
            "predicted_mid": round((idx + 0.5) / bins, 4),
            "observed_rate": round(sum(1 for y in ys if y) / len(ys), 4),
        })
    return out


def spearman(predicted: Sequence[float], actual: Sequence[float]) -> float:
    """Rank correlation, with average ranks for ties.

    Ties are the normal case here (most applications end at the same
    relevance), and the naive implementation that ignores them systematically
    overstates correlation.
    """
    n = len(predicted)
    if n < 2 or len(actual) != n:
        return 0.0

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: values[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rp, ra = ranks(predicted), ranks(actual)
    mp, ma = sum(rp) / n, sum(ra) / n
    num = sum((a - mp) * (b - ma) for a, b in zip(rp, ra))
    den = math.sqrt(sum((a - mp) ** 2 for a in rp) * sum((b - ma) ** 2 for b in ra))
    return round(num / den, 4) if den else 0.0


# --- the report -------------------------------------------------------------

MIN_SAMPLE = 10


@dataclass
class RankingReport:
    n: int
    positives: int
    base_rate: float
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    lift_at_5: float = 0.0
    lift_at_10: float = 0.0
    brier: float | None = None
    spearman: float = 0.0
    calibration: list[dict] = field(default_factory=list)
    funnel: dict[str, int] = field(default_factory=dict)
    underpowered: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "n": self.n, "positives": self.positives, "base_rate": self.base_rate,
            "ndcg_at_5": self.ndcg_at_5, "ndcg_at_10": self.ndcg_at_10,
            "precision_at_5": self.precision_at_5, "precision_at_10": self.precision_at_10,
            "lift_at_5": self.lift_at_5, "lift_at_10": self.lift_at_10,
            "brier": self.brier, "spearman": self.spearman,
            "calibration": self.calibration, "funnel": self.funnel,
            "underpowered": self.underpowered, "note": self.note,
            "score_kind": "match_score",
            "probability_note": "Match scores are not calibrated probabilities; Brier is withheld.",
        }


def evaluate(pairs: Iterable[tuple[float, str]],
             min_sample: int = MIN_SAMPLE) -> RankingReport:
    """Score the ranker against real outcomes.

    `pairs` is (predicted_score_0_to_1, furthest_stage_reached). Sorting
    happens here rather than being assumed of the caller, because every metric
    below depends on the list being in predicted order and a caller that
    forgot would get plausible-looking nonsense.
    """
    rows = sorted(pairs, key=lambda t: -t[0])
    n = len(rows)
    stages = [s for _, s in rows]
    scores = [s for s, _ in rows]
    rels = [float(relevance(s)) for s in stages]
    labels = [is_positive(s) for s in stages]
    positives = sum(1 for x in labels if x)
    funnel = dict(Counter(stages))
    base = round(positives / n, 4) if n else 0.0

    report = RankingReport(n=n, positives=positives, base_rate=base, funnel=funnel)
    min_sample = max(MIN_SAMPLE, min_sample)
    if n < min_sample:
        report.underpowered = True
        report.note = (f"Only {n} scored outcomes; metrics need at least "
                       f"{min_sample} to mean anything and are withheld.")
        return report
    if positives == 0:
        report.note = ("No application reached an OA or beyond yet, so there is "
                       "no positive signal to rank against.")
        return report

    report.ndcg_at_5 = ndcg_at_k(rels, 5)
    report.ndcg_at_10 = ndcg_at_k(rels, 10)
    report.precision_at_5 = precision_at_k(labels, 5)
    report.precision_at_10 = precision_at_k(labels, 10)
    report.lift_at_5 = lift_at_k(labels, 5)
    report.lift_at_10 = lift_at_k(labels, 10)
    # A heuristic match score is not a probability of progressing. Keep the
    # standalone Brier function for a future calibrated probability model.
    report.spearman = spearman(scores, rels)
    report.calibration = calibration_bins(scores, labels)
    report.note = (f"{positives}/{n} resolved or progressed applications reached {POSITIVE_FROM} "
                   f"or beyond (base rate {base:.0%}). Pending applications are excluded. "
                   "These observational results reflect only the roles you chose to apply to.")
    return report
