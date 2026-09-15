"""Gate, matcher, ranker, grounded explanation, and the end-to-end decision.

The assertions here are the product's promises stated as code: a blocked role
never outranks an eligible one, a skills-list keyword never scores like a
shipped project, and generated claims require known citations and matching
numeric values. These checks do not establish semantic entailment.
"""
from __future__ import annotations

import pytest

from roleradar import (
    constraints, decision, evidence as ev, explain, ranking, requirements as rq,
    skills_match,
)
from roleradar.models import (
    CandidateProfile, EvidenceUnit, Gate, HardConstraint, Requirement,
)

STUDENT = CandidateProfile(name="T", location="Houston, TX", graduation="May 2027",
                           seniority="student", degree_level="bachelors")


def _hc(kind, text="", value=None, cid="c1"):
    return HardConstraint(constraint_id=cid, kind=kind, text=text or kind,
                          source="jd:L1", value=value)


# --- hard-constraint gate ---------------------------------------------------

def test_sponsorship_blocks_only_when_the_candidate_needs_it():
    c = [_hc("sponsorship", "We do not sponsor.", "unavailable")]
    needs = constraints.evaluate(c, CandidateProfile(needs_sponsorship=True))
    doesnt = constraints.evaluate(c, CandidateProfile(needs_sponsorship=False))
    assert needs.passed is False and needs.blockers
    assert doesnt.passed is True


def test_unknown_work_authorization_is_flagged_never_guessed():
    """The system must not decide eligibility it was never told about."""
    gate = constraints.evaluate([_hc("sponsorship", value="unavailable")],
                                CandidateProfile(needs_sponsorship=None))
    assert gate.passed is True, "an unknown must not silently block"
    verdict = gate.verdicts[0]
    assert verdict.status == "unknown"
    assert verdict in gate.risks, "but it must still be surfaced and penalised"


def test_work_authorization_clause_alone_does_not_block_an_f1_student():
    """CPT/OPT is real work authorization; only a sponsorship ban disqualifies."""
    gate = constraints.evaluate(
        [_hc("work_authorization", "Must be authorized to work in the US.")],
        CandidateProfile(needs_sponsorship=True))
    assert gate.passed is True
    assert gate.verdicts[0].status == "risk"


def test_graduation_window_blocks_outside_and_passes_inside():
    inside = constraints.evaluate(
        [_hc("graduation_window", "Graduating in 2026 or 2027", "2026,2027")], STUDENT)
    outside = constraints.evaluate(
        [_hc("graduation_window", "Graduating in 2025", "2025")], STUDENT)
    assert inside.passed and inside.verdicts[0].status == "ok"
    assert not outside.passed


def test_graduation_window_is_unknown_when_the_candidate_has_no_date():
    gate = constraints.evaluate(
        [_hc("graduation_window", "2026 grads", "2026")],
        CandidateProfile(graduation=None))
    assert gate.verdicts[0].status == "unknown" and gate.passed


@pytest.mark.parametrize("value,expected", [
    ("May 2027", (2027, 5)), ("Spring 2027", (2027, 5)),
    ("2027", (2027, 6)), ("December 2026", (2026, 12)), (None, None),
])
def test_graduation_parsing(value, expected):
    assert constraints.parse_grad(value) == expected


def test_active_clearance_blocks_but_obtainable_clearance_only_warns():
    active = constraints.evaluate(
        [_hc("clearance", "Must have an active TS/SCI clearance")], STUDENT)
    obtainable = constraints.evaluate(
        [_hc("clearance", "Ability to obtain a security clearance")], STUDENT)
    assert not active.passed
    assert obtainable.passed and obtainable.verdicts[0].status == "risk"


def test_degree_shortfall_is_a_risk_not_a_veto():
    """Postings routinely over-state degree bars; vetoing on them hides jobs."""
    gate = constraints.evaluate([_hc("degree", "Master's degree required")], STUDENT)
    assert gate.passed and gate.verdicts[0].status == "risk"


def test_onsite_elsewhere_is_a_risk_when_open_to_relocating_and_a_block_when_not():
    c = [_hc("location", "Location: Seattle, WA", "onsite")]
    willing = constraints.evaluate(c, CandidateProfile(location="Houston, TX"))
    unwilling = constraints.evaluate(
        c, CandidateProfile(location="Houston, TX", open_to_relocate=False))
    assert willing.passed and willing.verdicts[0].status == "risk"
    assert not unwilling.passed


def test_unhandled_constraint_kind_is_surfaced_not_dropped():
    weird = HardConstraint(constraint_id="c9", kind="mystery",  # type: ignore[arg-type]
                           text="Must own a boat", source="jd:L3")
    gate = constraints.evaluate([weird], STUDENT)
    assert gate.verdicts[0].status == "unknown" and gate.passed


def test_risk_penalty_is_capped():
    many = [_hc(k, cid=f"c{i}") for i, k in enumerate(
        ("clearance", "citizenship", "sponsorship", "graduation_window",
         "degree", "location"))]
    gate = Gate(passed=True, verdicts=tuple(
        constraints.ConstraintVerdict(c.constraint_id, c.kind, "risk", "r")
        for c in many))
    assert constraints.risk_penalty(gate) == 0.30


# --- skill coverage ---------------------------------------------------------

DEMO = EvidenceUnit("ev1", "project", "JobEngine",
                    "Built an ingest pipeline in Python on PostgreSQL",
                    "projects[0].bullets[0]", ("python", "postgresql"))
LISTED = EvidenceUnit("ev2", "skill", "Languages", "Languages: Python, Java",
                      "skills.Languages", ("python", "java"))


def _cov(req, units):
    return skills_match.cover_requirement(req, skills_match._index_evidence(units))


def test_demonstrated_outscores_listed():
    req = Requirement("r1", "Python", "python")
    assert _cov(req, [DEMO]).score > _cov(req, [LISTED]).score


def test_listed_only_is_partial_and_says_so():
    cov = _cov(Requirement("r1", "Java", "java"), [DEMO, LISTED])
    assert cov.status == "partial"
    assert "no project" in cov.rationale.lower()


def test_implied_skill_is_credited_below_a_direct_mention():
    req = Requirement("r1", "SQL", "sql")
    cov = _cov(req, [DEMO])          # postgresql implies sql
    assert cov.status == "strong" and cov.score == skills_match._IMPLIED
    assert cov.evidence_ids == ("ev1",)


def test_missing_skill_cites_nothing_and_scores_zero():
    cov = _cov(Requirement("r1", "Rust", "rust"), [DEMO, LISTED])
    assert cov.status == "missing" and cov.score == 0.0 and cov.evidence_ids == ()


def test_alternatives_are_satisfied_by_the_best_member():
    req = Requirement("r1", "Python or Go", "go", alternatives=("python",))
    cov = _cov(req, [DEMO])
    assert cov.status == "strong"
    assert cov.skill == "python", "reports which alternative qualified"
    assert "Satisfied via python" in cov.rationale


def test_every_nonzero_coverage_cites_evidence():
    """The core invariant: no credit without a citation."""
    reqs = [Requirement(f"r{i}", s, s) for i, s in
            enumerate(("python", "sql", "java", "rust"))]
    for cov in skills_match.cover_all(reqs, [DEMO, LISTED]):
        assert (cov.score > 0) == bool(cov.evidence_ids)


def test_aggregate_treats_absent_requirements_as_neutral_not_failed():
    required, preferred = skills_match.aggregate([])
    assert (required, preferred) == (1.0, 1.0)


def test_gaps_lists_required_misses_worst_first():
    reqs = [Requirement("r1", "Rust", "rust"),
            Requirement("r2", "Python", "python"),
            Requirement("r3", "Kubernetes", "kubernetes", importance="preferred")]
    covs = skills_match.cover_all(reqs, [DEMO])
    gaps = skills_match.gaps(covs)
    assert [g.skill for g in gaps] == ["rust"]


# --- ranking ----------------------------------------------------------------

def test_weights_sum_to_one():
    assert abs(sum(ranking.WEIGHTS.values()) - 1.0) < 1e-9


def test_seniority_fit_penalises_reaching_up_more_than_down():
    up = ranking.seniority_fit(STUDENT, rq.JobRequirements("k", seniority="senior"))
    down = ranking.seniority_fit(CandidateProfile(seniority="senior"),
                                 rq.JobRequirements("k", seniority="intern"))
    assert up < down


def test_unknown_seniority_is_neutral_but_not_free():
    fit = ranking.seniority_fit(STUDENT, rq.JobRequirements("k", seniority="unknown"))
    assert 0.0 < fit < 1.0


def test_semantic_similarity_is_bounded_and_self_consistent():
    assert ranking.semantic_similarity("", "anything") == 0.0
    same = ranking.semantic_similarity("python fastapi postgres",
                                       "python fastapi postgres")
    assert 0.99 <= same <= 1.0


def test_apply_requires_real_required_coverage_not_just_a_good_average():
    """A high blended score with a gutted required half is a stretch, not an apply."""
    gate = Gate(passed=True)
    # 0.55 required coverage with everything else perfect clears the score
    # threshold (0.5*0.55 + 0.15 + 0.2 + 0.15 = 0.775) but sits under the
    # required-coverage floor, which is exactly the case the floor exists for.
    breakdown = ranking.ScoreBreakdown(
        required_coverage=0.55, preferred_coverage=1.0, semantic_similarity=1.0,
        seniority_fit=1.0, risk_penalty=0.0, weights=dict(ranking.WEIGHTS))
    score = ranking.score_of(breakdown)
    assert score >= ranking.APPLY_THRESHOLD
    assert breakdown.required_coverage < ranking.APPLY_MIN_REQUIRED
    assert ranking.verdict_of(score, gate, breakdown) == "stretch"

    # ...and the same score with the required half genuinely covered is an apply.
    covered = ranking.ScoreBreakdown(
        required_coverage=0.90, preferred_coverage=1.0, semantic_similarity=1.0,
        seniority_fit=1.0, risk_penalty=0.0, weights=dict(ranking.WEIGHTS))
    assert ranking.verdict_of(ranking.score_of(covered), gate, covered) == "apply"


def test_a_failed_gate_always_produces_blocked():
    breakdown = ranking.ScoreBreakdown(1.0, 1.0, 1.0, 1.0, 0.0, dict(ranking.WEIGHTS))
    gate = Gate(passed=False, verdicts=(
        constraints.ConstraintVerdict("c1", "sponsorship", "blocked", "no"),))
    assert ranking.verdict_of(1.0, gate, breakdown) == "blocked"


# --- grounded explanation ---------------------------------------------------

EVIDENCE = {"ev1": DEMO, "ev2": LISTED}


def test_claim_citing_an_unknown_id_is_dropped():
    kept, dropped = explain.validate_grounding(
        [{"text": "You know Rust.", "evidence_ids": ["ev999"]}], EVIDENCE)
    assert kept == [] and "unknown evidence id" in dropped[0]["drop_reason"]


def test_uncited_claim_is_dropped():
    kept, dropped = explain.validate_grounding(
        [{"text": "You are a great fit.", "evidence_ids": []}], EVIDENCE)
    assert kept == [] and dropped[0]["drop_reason"] == "no evidence cited"


@pytest.mark.parametrize("number", ["0", "1", "2", "3", "4", "5", "7"])
def test_fabricated_number_is_dropped_even_with_a_valid_citation(number):
    """The failure mode this whole layer exists to stop."""
    kept, dropped = explain.validate_grounding(
        [{"text": f"You have {number} years of Python experience.",
          "evidence_ids": ["ev1"]}], EVIDENCE)
    assert kept == []
    assert number in dropped[0]["drop_reason"]


@pytest.mark.parametrize("source_number,claim_number,accepted", [
    ("1", "10", False), ("10", "100", False), ("100", "1", False),
    ("10.0", "10", True), ("35,000", "35000", True),
    ("35000", "35", False), ("-10", "10", False),
])
def test_numeric_citations_preserve_magnitude_and_sign(source_number, claim_number, accepted):
    unit = EvidenceUnit("ev3", "project", "Pipeline",
                        f"Processed {source_number} listings", "projects[0]", ())
    kept, dropped = explain.validate_grounding(
        [{"text": f"Processed {claim_number} listings", "evidence_ids": ["ev3"]}],
        {"ev3": unit})
    assert bool(kept) is accepted
    assert bool(dropped) is not accepted


@pytest.mark.parametrize("claim", [None, 42, "text", [], {"text": []},
                                    {"text": "Python", "evidence_ids": "ev1"},
                                    {"text": "Python", "evidence_ids": [{}]}])
def test_malformed_claims_are_dropped_without_crashing(claim):
    kept, dropped = explain.validate_grounding([claim], EVIDENCE)
    assert kept == [] and "malformed" in dropped[0]["drop_reason"]


def test_number_in_an_uncited_evidence_unit_does_not_support_a_claim():
    unrelated = EvidenceUnit("ev3", "project", "Other", "Built 3 services", "other", ())
    kept, dropped = explain.validate_grounding(
        [{"text": "You have 3 years of Python experience", "evidence_ids": ["ev1"]}],
        {**EVIDENCE, "ev3": unrelated})
    assert kept == [] and dropped


def test_number_present_in_the_cited_evidence_is_allowed():
    unit = EvidenceUnit("ev3", "project", "JobEngine",
                        "Deduplicated 32735 listings", "projects[0].bullets[0]",
                        ("python",))
    kept, dropped = explain.validate_grounding(
        [{"text": "You deduplicated 32735 listings.", "evidence_ids": ["ev3"]}],
        {"ev3": unit})
    assert len(kept) == 1 and dropped == []


def test_valid_claim_survives():
    kept, _ = explain.validate_grounding(
        [{"text": "You have shipped Python on PostgreSQL.",
          "evidence_ids": ["ev1"]}], EVIDENCE)
    assert kept[0]["evidence_ids"] == ["ev1"]


def test_explanation_falls_back_to_deterministic_without_a_provider(monkeypatch):
    monkeypatch.setattr(explain.llm_client, "available", lambda: False)
    d = _decide_fixture()
    text, source, _cited, dropped = explain.explain(d, _units(), use_llm=True)
    assert source == "deterministic" and dropped == []
    assert "Match score" in text


def test_llm_output_with_only_ungrounded_claims_is_discarded(monkeypatch):
    monkeypatch.setattr(explain.llm_client, "available", lambda: True)
    monkeypatch.setattr(explain.llm_client, "complete_json", lambda *a, **k: {
        "summary": "Strong fit.",
        "claims": [{"text": "You led a team of 12 engineers.",
                    "evidence_ids": ["ev_nope"]}],
        "next_steps": [],
    })
    d = _decide_fixture()
    text, source, _cited, dropped = explain.explain(d, _units(), use_llm=True)
    assert source == "deterministic", "nothing survived, so publish nothing of it"
    assert dropped and "12 engineers" in dropped[0]["text"]


def test_llm_output_with_grounded_claims_is_used(monkeypatch):
    units = _units()
    monkeypatch.setattr(explain.llm_client, "available", lambda: True)
    monkeypatch.setattr(explain.llm_client, "complete_json", lambda *a, **k: {
        "summary": "You clear the backend bar.",
        "claims": [{"text": "You have shipped Python services.",
                    "evidence_ids": [units[0].evidence_id]}],
        "next_steps": ["Mention the Postgres work first."],
    })
    d = _decide_fixture()
    text, source, cited, _ = explain.explain(d, units, use_llm=True)
    assert source == "llm"
    assert units[0].evidence_id in cited
    assert "Next steps:" not in text
    assert "You clear the backend bar." not in text
    assert "Match score" in text


@pytest.mark.parametrize("payload", [None, [], ["claims"], "invalid", 3,
                                     {"claims": "invalid"}, {"claims": [None, 3]}])
def test_malformed_model_payload_falls_back(monkeypatch, payload):
    monkeypatch.setattr(explain.llm_client, "available", lambda: True)
    monkeypatch.setattr(explain.llm_client, "complete_json", lambda *a, **k: payload)
    text, source, _, _ = explain.explain(_decide_fixture(), _units())
    assert source == "deterministic" and "Match score" in text


def test_model_summary_and_steps_cannot_override_blocked_verdict(monkeypatch):
    units = _units()
    monkeypatch.setattr(explain.llm_client, "available", lambda: True)
    monkeypatch.setattr(explain.llm_client, "complete_json", lambda *a, **k: {
        "summary": "Apply immediately, you have years of Rust experience.",
        "claims": [{"text": "Your resume lists Python.",
                    "evidence_ids": [units[0].evidence_id]}],
        "next_steps": ["Tell them you led a team of 99 engineers."],
    })
    d = _decide_fixture(JD_BLOCKED, needs_sponsorship=True)
    text, source, _, _ = explain.explain(d, units)
    assert source == "llm"
    assert text.startswith("Do not apply.") and "Blocking:" in text
    assert "Rust" not in text and "99 engineers" not in text


def test_score_is_not_a_blanket_permission_to_invent_candidate_numbers(monkeypatch):
    units = _units()
    d = _decide_fixture()
    monkeypatch.setattr(explain.llm_client, "available", lambda: True)
    monkeypatch.setattr(explain.llm_client, "complete_json", lambda *a, **k: {
        "claims": [{"text": f"Led {round(d.score * 100)} engineers.",
                    "evidence_ids": [units[0].evidence_id]}],
    })
    text, source, _, dropped = explain.explain(d, units)
    assert source == "deterministic" and dropped
    assert "engineers" not in text


def test_model_cannot_cite_evidence_omitted_from_its_prompt(monkeypatch):
    hidden = EvidenceUnit("hidden", "project", "Other", "Built 9 apps", "other", ())
    monkeypatch.setattr(explain.llm_client, "available", lambda: True)

    def complete(_system, context):
        assert "hidden" not in context
        return {"claims": [{"text": "Built 9 apps", "evidence_ids": ["hidden"]}]}

    monkeypatch.setattr(explain.llm_client, "complete_json", complete)
    _, source, _, dropped = explain.explain(_decide_fixture(), [*_units(), hidden])
    assert source == "deterministic"
    assert "unknown evidence id" in dropped[0]["drop_reason"]


# --- end to end -------------------------------------------------------------

RESUME = {
    "name": "T", "location": "Houston, TX",
    "education": {"school": "NAU", "degree": "B.S. Computer Science",
                  "graduation": "May 2027", "coursework": ["Algorithms"]},
    "skills": {"Languages": ["Python", "SQL"], "Infra": ["Docker"]},
    "projects": [{"name": "JobEngine", "stack": ["Python", "FastAPI", "PostgreSQL"],
                  "dates": "2026",
                  "bullets": ["Built an ingest pipeline in Python on PostgreSQL"]}],
}
JD_OK = ("Minimum Qualifications\n- Python\n- Experience with SQL\n"
         "Preferred Qualifications\n- Docker\n")
JD_BLOCKED = JD_OK + "\nWe are unable to provide visa sponsorship.\n"


def _units():
    return ev.extract_evidence(RESUME)


def _decide_fixture(jd=JD_OK, needs_sponsorship=False):
    profile = ev.profile_from_resume(RESUME, needs_sponsorship=needs_sponsorship,
                                     seniority="student")
    return decision.decide({"dedup_key": "j1", "title": "Software Engineer Intern",
                            "company": "Acme"}, profile, _units(),
                           jd_text=jd, use_llm=False)


def test_eligible_candidate_gets_a_citeable_apply():
    d = _decide_fixture()
    assert d.verdict in ("apply", "stretch")
    assert d.gate.passed
    assert any(c.evidence_ids for c in d.coverages)
    assert d.explanation_source == "deterministic"


def test_sponsorship_need_flips_the_same_role_to_blocked():
    ok = _decide_fixture(JD_BLOCKED, needs_sponsorship=False)
    blocked = _decide_fixture(JD_BLOCKED, needs_sponsorship=True)
    assert ok.verdict != "blocked"
    assert blocked.verdict == "blocked"
    assert blocked.score == ok.score, "the gate vetoes; it does not alter the score"


def test_blocked_roles_sort_below_eligible_ones_regardless_of_score():
    jobs = [{"dedup_key": "blocked", "title": "Software Engineer Intern",
             "company": "A", "sponsor_tier": "does_not_sponsor"},
            {"dedup_key": "open", "title": "Data Entry Clerk", "company": "B"}]
    profile = ev.profile_from_resume(RESUME, needs_sponsorship=True)
    ranked = decision.decide_many(jobs, RESUME, profile, use_llm=False)
    assert ranked[-1].job_key == "blocked"


def test_decision_serialises_to_json_safe_primitives():
    import json
    payload = _decide_fixture().as_dict()
    json.dumps(payload)
    assert set(payload) >= {"verdict", "score", "gate", "coverages", "breakdown"}


def test_confidence_is_lower_without_a_description():
    with_jd = _decide_fixture(JD_OK)
    without = _decide_fixture("")
    assert without.confidence < with_jd.confidence
