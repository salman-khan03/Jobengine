from types import SimpleNamespace

from jobengine.sponsor_index import SponsorIndex, _tier_for
from jobengine.normalize import normalize_company


def _fake_job(company, sponsorship_simplify=""):
    return SimpleNamespace(
        company_norm=normalize_company(company),
        sponsorship_simplify=sponsorship_simplify,
        sponsor_tier="unknown",
        sponsor_lca_count=0,
        sponsor_match="",
    )


def test_tier_thresholds():
    assert _tier_for(10000) == "very_high"
    assert _tier_for(5000) == "very_high"
    assert _tier_for(4999) == "high"
    assert _tier_for(1000) == "high"
    assert _tier_for(999) == "medium"
    assert _tier_for(1) == "low"
    assert _tier_for(0) == "unknown"


def test_seed_index_recognizes_known_sponsors():
    idx = SponsorIndex.from_seed()
    job = _fake_job("Google")
    idx.annotate(job)
    assert job.sponsor_tier == "very_high"
    assert job.sponsor_match.startswith("index:seed")


def test_explicit_no_sponsorship_overrides_index():
    idx = SponsorIndex.from_seed()
    job = _fake_job("Google", sponsorship_simplify="Does Not Offer Sponsorship")
    idx.annotate(job)
    assert job.sponsor_tier == "does_not_sponsor"


def test_citizen_only_overrides_index():
    idx = SponsorIndex.from_seed()
    job = _fake_job("Amazon", sponsorship_simplify="U.S. Citizenship is Required")
    idx.annotate(job)
    assert job.sponsor_tier == "citizen_only"


def test_unknown_company_is_unknown_not_no():
    idx = SponsorIndex.from_seed()
    job = _fake_job("Totally Unheard Of Startup XYZ")
    idx.annotate(job)
    assert job.sponsor_tier == "unknown"
    assert job.sponsor_tier != "does_not_sponsor"


def test_simplify_offers_used_when_not_in_index():
    idx = SponsorIndex.from_seed()
    job = _fake_job("Some Niche Company", sponsorship_simplify="Offers Sponsorship")
    idx.annotate(job)
    assert job.sponsor_tier == "offers"


def test_dol_csv_overrides_seed_with_real_counts(tmp_path):
    csv_path = tmp_path / "lca.csv"
    csv_path.write_text(
        "EMPLOYER_NAME,CASE_STATUS\n"
        "GOOGLE LLC,Certified\n" * 50 +
        "GOOGLE LLC,Denied\n"  # should not count
    )
    idx = SponsorIndex.from_seed()
    n = idx.load_dol_csv(str(csv_path))
    assert n == 1
    job = _fake_job("Google")
    idx.annotate(job)
    assert job.sponsor_lca_count == 50
    assert job.sponsor_match == "index:dol"
