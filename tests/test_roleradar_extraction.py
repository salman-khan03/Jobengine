"""Extraction layer: taxonomy, resume evidence, posting requirements.

These tests encode the *judgement calls* in the extractors, not just their
happy paths -- a regression in any assertion below changes what advice a real
person gets about a real application.
"""
from __future__ import annotations

import pytest

from roleradar import evidence as ev, requirements as rq, taxonomy


# --- taxonomy ---------------------------------------------------------------

def test_aliases_resolve_to_canonical_names():
    assert taxonomy.canonical("Postgres") == "postgresql"
    assert taxonomy.canonical("k8s") == "kubernetes"
    assert taxonomy.canonical("NodeJS") == "node.js"
    assert taxonomy.canonical("nonexistent-framework") is None


def test_canonical_name_is_never_shadowed_by_another_skills_alias():
    # "aws lambda" is an alias of serverless and "lambda" an alias of aws;
    # neither may steal the canonical "aws" entry.
    assert taxonomy.canonical("aws") == "aws"
    assert taxonomy.canonical("serverless") == "serverless"


def test_extraction_prefers_longest_match_and_survives_punctuation():
    skills = taxonomy.extract_skills(
        "Built with Next.js and machine learning; also C++ and CI/CD.")
    assert "next.js" in skills
    assert "machine learning" in skills
    assert "c++" in skills
    assert "ci/cd" in skills


def test_extraction_is_ordered_and_deduplicated():
    twice = taxonomy.extract_skills("python, then more Python, then python")
    assert twice == ("python",)


def test_extraction_respects_word_boundaries():
    # "go" must not fire inside "going", nor "r" inside every word.
    assert "go" not in taxonomy.extract_skills("We are going to ship")
    assert "r" not in taxonomy.extract_skills("regular remote role")


def test_implication_closure_is_transitive():
    closure = taxonomy.closure("next.js")
    assert {"next.js", "react", "javascript"} <= closure


def test_expand_marks_direct_over_implied():
    expanded = taxonomy.expand(("next.js", "react"))
    assert expanded["react"] == "direct", "explicitly named beats inferred"
    assert expanded["javascript"] == "implied"


def test_implies_table_has_no_unknown_skills():
    """A typo in IMPLIES would silently create an unreachable edge."""
    for skill, implied in taxonomy.IMPLIES.items():
        assert skill in taxonomy.CANONICAL_SKILLS, skill
        for target in implied:
            assert target in taxonomy.CANONICAL_SKILLS, f"{skill} -> {target}"


def test_implies_table_is_acyclic():
    for skill in taxonomy.IMPLIES:
        # closure() tolerates cycles; this asserts there aren't any, since a
        # cycle would mean two skills each "prove" the other.
        assert skill in taxonomy.closure(skill)
        for target in taxonomy.IMPLIES[skill]:
            assert skill not in taxonomy.closure(target), f"cycle {skill}<->{target}"


# --- resume evidence --------------------------------------------------------

RESUME = {
    "name": "Test Candidate",
    "location": "Houston, TX",
    "education": {"school": "NAU", "degree": "B.S. Computer Science",
                  "graduation": "May 2027", "coursework": ["Algorithms"]},
    "skills": {"Languages": ["Python", "Java"], "Infra": ["Docker"]},
    "projects": [{
        "name": "JobEngine", "stack": ["Python", "FastAPI", "PostgreSQL"],
        "dates": "Jul 2026 - Present",
        "bullets": ["Deduplicated 32735 listings into 32388 unique rows",
                    "Added a Redis cache measured at 14.46ms p95"],
    }],
    "experience": [{
        "title": "Grader", "org": "NAU", "dates": "2026",
        "bullets": ["Reviewed student Java submissions"],
    }],
}


def test_every_unit_is_verbatim_and_traceable():
    units = ev.extract_evidence(RESUME)
    bullet = next(u for u in units if u.source == "projects[0].bullets[0]")
    assert bullet.text == "Deduplicated 32735 listings into 32388 unique rows"
    assert bullet.label == "JobEngine"
    assert bullet.kind == "project"


def test_evidence_ids_are_content_addressed_not_positional():
    """Reordering projects must not invalidate citations stored months ago."""
    reordered = {**RESUME, "projects": list(RESUME["projects"])}
    first = {u.text: u.evidence_id for u in ev.extract_evidence(RESUME)}
    second = {u.text: u.evidence_id for u in ev.extract_evidence(reordered)}
    assert first == second


def test_stack_contributes_skills_to_each_bullet():
    units = ev.extract_evidence(RESUME)
    bullet = next(u for u in units if u.source == "projects[0].bullets[1]")
    assert "redis" in bullet.skills
    assert "postgresql" in bullet.skills, "declared stack applies to its bullets"


def test_skill_section_units_are_kind_skill():
    units = ev.extract_evidence(RESUME)
    listed = [u for u in units if u.kind == "skill"]
    assert listed, "a skills section must produce citable units"
    assert all(u.source.startswith("skills.") for u in listed)


def test_education_unit_carries_graduation():
    units = ev.extract_evidence(RESUME)
    edu = next(u for u in units if u.kind == "education")
    assert "May 2027" in edu.text


def test_profile_never_guesses_work_authorization():
    profile = ev.profile_from_resume(RESUME)
    assert profile.needs_sponsorship is None
    assert profile.work_authorization == "unknown"
    assert profile.graduation == "May 2027"
    assert profile.degree_level == "bachelors"


def test_profile_overrides_apply():
    profile = ev.profile_from_resume(RESUME, needs_sponsorship=True,
                                     location="Austin, TX")
    assert profile.needs_sponsorship is True
    assert profile.location == "Austin, TX"


@pytest.mark.parametrize("degree,expected", [
    ("B.S. Computer Science", "bachelors"),
    ("Master of Science in CS", "masters"),
    ("PhD in Machine Learning", "phd"),
    ("Associate of Applied Science", "associates"),
])
def test_degree_levels(degree, expected):
    resume = {**RESUME, "education": {**RESUME["education"], "degree": degree}}
    assert ev.profile_from_resume(resume).degree_level == expected


# --- posting requirements ---------------------------------------------------

JD = """Software Engineer Intern, Backend

Responsibilities
- Ship services that talk to Kafka.

Minimum Qualifications
- Currently enrolled in a Bachelor's degree program
- Graduating between December 2026 and August 2027
- Strong programming skills in Python or Go
- Experience with SQL and relational databases

Preferred Qualifications
- Familiarity with Kubernetes
- Exposure to React is a plus

We are unable to provide visa sponsorship for this position.
"""


@pytest.fixture()
def parsed():
    return rq.extract_requirements(
        {"dedup_key": "k", "title": "Software Engineer Intern",
         "company": "Acme", "locations": "Seattle, WA"}, JD)


def _req(parsed, skill):
    return next((r for r in parsed.requirements
                 if r.canonical_skill == skill or skill in r.alternatives), None)


def test_section_headers_split_required_from_preferred(parsed):
    assert _req(parsed, "sql").importance == "required"
    assert _req(parsed, "kubernetes").importance == "preferred"


def test_bulleted_line_is_never_treated_as_a_section_header(parsed):
    """'- Exposure to React is a plus' contains a preferred-section phrase.

    Treating it as a header dropped its skills entirely and reclassified
    everything after it -- the regression this test exists for.
    """
    react = _req(parsed, "react")
    assert react is not None
    assert react.importance == "preferred"


def test_responsibilities_prose_is_not_a_hard_requirement(parsed):
    assert _req(parsed, "kafka").importance == "preferred"


def test_disjunction_becomes_one_requirement_with_alternatives(parsed):
    python = _req(parsed, "python")
    assert python.alternatives == ("go",), "'Python or Go' is one ask"
    assert _req(parsed, "go") is python


def test_conjunction_is_not_collapsed():
    reqs = rq.find_requirements("- Experience with Docker and Kubernetes")
    skills = {r.canonical_skill for r in reqs}
    assert skills == {"docker", "kubernetes"}, "'and' means two real asks"


def test_trailing_hedge_after_conjunction_stays_conjunctive():
    reqs = rq.find_requirements("- Kubernetes and Docker, or similar tooling")
    assert len({r.canonical_skill for r in reqs}) == 2


@pytest.mark.parametrize("line", [
    "We are unable to provide visa sponsorship for this role.",
    "This position is not eligible for visa sponsorship.",
    "Applicants must be authorized to work without sponsorship.",
    "No visa sponsorship is available.",
    "We will not sponsor applicants for work visas.",
    # Contracted forms. An earlier pattern built the negation as
    # "(can|will)\s*n't", which cannot match "can't" -- the "can" branch
    # consumes the n. Every spelling below is one a real posting uses.
    "We cannot provide visa sponsorship.",
    "We can't sponsor visas for this role.",
    "We won't be able to sponsor a visa.",
    "We don't offer visa sponsorship.",
    "This company does not provide visa sponsorship.",
    "Sponsorship isn't available.",
])
def test_sponsorship_negatives_are_all_caught(line):
    found = rq.find_constraints(line)
    assert any(c.kind == "sponsorship" and c.value == "unavailable" for c in found), line


def test_sponsorship_positive_is_recognised():
    found = rq.find_constraints("Visa sponsorship is available for this role.")
    assert any(c.kind == "sponsorship" and c.value == "available" for c in found)


def test_contradictory_sponsorship_resolves_to_the_safe_reading():
    found = rq.find_constraints(
        "Sponsorship is available.\nWe are unable to provide visa sponsorship.")
    spon = [c for c in found if c.kind == "sponsorship"]
    assert len(spon) == 1 and spon[0].value == "unavailable"


def test_graduation_window_years_are_parsed(parsed):
    grad = next(c for c in parsed.constraints if c.kind == "graduation_window")
    assert grad.value == "2026,2027"


def test_constraints_carry_line_provenance(parsed):
    spon = next(c for c in parsed.constraints if c.kind == "sponsorship")
    assert spon.source.startswith("jd:L")


def test_repeated_constraint_language_is_reported_once():
    text = "\n".join(["We do not sponsor visas."] * 4)
    assert len([c for c in rq.find_constraints(text) if c.kind == "sponsorship"]) == 1


def test_sponsor_tier_promotes_to_a_constraint_when_the_posting_is_silent():
    parsed = rq.extract_requirements(
        {"dedup_key": "k", "title": "SWE", "company": "X",
         "sponsor_tier": "does_not_sponsor"}, "Requirements\n- Python")
    spon = next(c for c in parsed.constraints if c.kind == "sponsorship")
    assert spon.value == "unavailable"
    assert spon.source == "sponsor_index", "H-1B filing history, not JD prose"


def test_jd_sponsorship_language_wins_over_the_tier_index():
    parsed = rq.extract_requirements(
        {"dedup_key": "k", "title": "SWE", "company": "X",
         "sponsor_tier": "does_not_sponsor"},
        "Visa sponsorship is available for this role.")
    spon = [c for c in parsed.constraints if c.kind == "sponsorship"]
    assert len(spon) == 1 and spon[0].value == "available"


def test_title_skills_become_requirements_without_a_description():
    parsed = rq.extract_requirements(
        {"dedup_key": "k", "title": "Backend Engineer, Go", "company": "X"}, "")
    go = next(r for r in parsed.requirements if r.canonical_skill == "go")
    assert go.importance == "required" and go.source == "title"


@pytest.mark.parametrize("title,expected", [
    ("Software Engineer Intern", "intern"),
    ("New Grad Software Engineer", "new_grad"),
    ("Senior Backend Engineer", "senior"),
    ("Staff Software Engineer", "staff"),
    ("Software Engineer", "unknown"),
])
def test_seniority_inference(title, expected):
    assert rq.infer_seniority(title) == expected


def test_min_years_takes_the_smallest_stated_bar():
    parsed = rq.extract_requirements(
        {"dedup_key": "k", "title": "SWE", "company": "X"},
        "Minimum Qualifications\n- 2+ years of experience\n"
        "Preferred\n- 5+ years of experience")
    assert parsed.min_years == 2.0


def test_empty_description_degrades_without_raising():
    parsed = rq.extract_requirements({"dedup_key": "k", "title": "", "company": ""}, "")
    assert parsed.requirements == () and parsed.seniority == "unknown"
