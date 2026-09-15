"""DOL H-1B LCA cross-reference.

Simplify's own `sponsorship` field is "Other" (unknown) on ~99% of listings.
This index answers the question that field can't: does this employer have a
real history of sponsoring? Two data sources, one interface:

  - from_seed(): curated list of established high-volume sponsors, so the
    pipeline is useful offline with zero setup (match = "index:seed").
  - load_dol_csv(): a real DOL OFLC LCA disclosure file — certified-filing
    counts per employer override the seed (match = "index:dol").

Precedence in annotate(): an explicit "does not sponsor"/"citizens only"
statement on the posting always wins over the index — a company that
sponsors in general may still post citizen-only roles. A company simply
absent from the index is "unknown", never "does_not_sponsor"; absence of
evidence is not evidence of absence, and the tests enforce that.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

from .normalize import normalize_company

# Certified-LCA-count thresholds -> tier.
def _tier_for(count: int) -> str:
    if count >= 5000:
        return "very_high"
    if count >= 1000:
        return "high"
    if count >= 100:
        return "medium"
    if count >= 1:
        return "low"
    return "unknown"


# Curated seed: employers with consistently heavy LCA filing volume.
# Tiers are approximate (count stays 0 / match "index:seed") until a real
# DOL CSV is loaded. Staffing agencies are tagged so query.py can exclude
# them by default — high filing volume there doesn't mean direct hiring.
_SEED_VERY_HIGH = [
    "google", "amazon", "microsoft", "meta", "apple", "nvidia", "oracle",
    "ibm", "intel", "salesforce", "cisco", "qualcomm", "jpmorgan chase",
    "goldman sachs", "capital one", "walmart", "deloitte", "ernst and young",
]
_SEED_HIGH = [
    "adobe", "uber", "lyft", "tesla", "netflix", "airbnb", "stripe",
    "bloomberg", "morgan stanley", "paypal", "visa", "mastercard",
    "linkedin", "servicenow", "workday", "databricks", "snowflake",
    "atlassian", "doordash", "pinterest", "square", "block", "intuit",
    "vmware", "dell", "hp", "texas instruments", "amd", "broadcom",
    "citadel", "two sigma", "bank of america", "wells fargo", "american express",
]
_SEED_AGENCIES = [
    "infosys", "tata consultancy services", "cognizant", "wipro",
    "hcl america", "tech mahindra", "accenture", "capgemini",
]


@dataclass
class SponsorIndex:
    # company_norm -> (tier, lca_count, match_source)
    _entries: dict[str, tuple[str, int, str]] = field(default_factory=dict)

    @classmethod
    def from_seed(cls) -> "SponsorIndex":
        idx = cls()
        for name in _SEED_VERY_HIGH:
            idx._entries[name] = ("very_high", 0, "index:seed")
        for name in _SEED_HIGH:
            idx._entries[name] = ("high", 0, "index:seed")
        for name in _SEED_AGENCIES:
            idx._entries[name] = ("high", 0, "index:seed:agency")
        return idx

    def load_dol_csv(self, path: str) -> int:
        """Load certified-LCA counts from a DOL OFLC disclosure CSV.

        Only CASE_STATUS == Certified counts; denials/withdrawals aren't
        evidence of sponsorship. Overrides seed entries with real numbers.
        Returns the number of distinct employers loaded.
        """
        counts: dict[str, int] = {}
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            for rec in csv.DictReader(fh):
                if (rec.get("CASE_STATUS") or "").strip().lower() != "certified":
                    continue
                key = normalize_company(rec.get("EMPLOYER_NAME", ""))
                if key:
                    counts[key] = counts.get(key, 0) + 1
        for key, n in counts.items():
            self._entries[key] = (_tier_for(n), n, "index:dol")
        return len(counts)

    def annotate(self, job) -> None:
        """Set sponsor_tier / sponsor_lca_count / sponsor_match on a job."""
        stated = (job.sponsorship_simplify or "").lower()
        # Explicit statements on the posting beat any historical index data.
        if "does not offer" in stated or "no sponsorship" in stated:
            job.sponsor_tier = "does_not_sponsor"
            job.sponsor_match = "simplify:stated"
            return
        if "citizen" in stated or "clearance" in stated:
            job.sponsor_tier = "citizen_only"
            job.sponsor_match = "simplify:stated"
            return

        entry = self._entries.get(job.company_norm)
        if entry:
            job.sponsor_tier, job.sponsor_lca_count, job.sponsor_match = entry
            return
        if "offers sponsorship" in stated:
            job.sponsor_tier = "offers"
            job.sponsor_match = "simplify:offers"
            return
        # Not in the index and nothing stated: unknown — never "no".
        job.sponsor_tier = "unknown"
