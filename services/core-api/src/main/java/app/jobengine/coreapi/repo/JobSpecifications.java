package app.jobengine.coreapi.repo;

import app.jobengine.coreapi.domain.Job;
import app.jobengine.coreapi.web.SearchQuery;
import jakarta.persistence.criteria.Predicate;
import org.springframework.data.jpa.domain.Specification;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Composable filter predicates for job search.
 *
 * <p>Criteria API rather than a hand-built query string: the filters are
 * independently optional, so string concatenation would mean tracking whether
 * the next clause needs {@code WHERE} or {@code AND} — and every such
 * concatenation is a place SQL injection gets introduced. Every value below is
 * bound as a parameter.
 */
public final class JobSpecifications {

    private JobSpecifications() {
    }

    /** Only listings the pipeline currently considers live. */
    public static Specification<Job> active() {
        return (root, q, cb) -> cb.and(
                cb.equal(root.get("active"), 1),
                cb.equal(root.get("isVisible"), 1));
    }

    /**
     * Substring match against the JSON-encoded locations array.
     *
     * <p>Honest limitation: this is a {@code LIKE '%...%'} against a JSON string
     * column, so it cannot use a B-tree index and it will match "York" inside
     * "New York". Correct location filtering needs the pipeline to normalize
     * locations into a separate table. Recorded in known-limitations.md;
     * acceptable at 35k rows, not at 10x that.
     */
    public static Specification<Job> location(List<String> locations) {
        return (root, q, cb) -> {
            if (locations == null || locations.isEmpty()) return null;
            List<Predicate> any = new ArrayList<>();
            for (String loc : locations) {
                any.add(cb.like(cb.lower(root.get("locations")),
                        "%" + loc.toLowerCase(Locale.ROOT) + "%"));
            }
            return cb.or(any.toArray(new Predicate[0]));
        };
    }

    /** Sponsorship tier, the product's whole reason to exist. Indexed. */
    public static Specification<Job> sponsorTier(List<String> tiers) {
        return (root, q, cb) -> {
            if (tiers == null || tiers.isEmpty()) return null;
            return root.get("sponsorTier").in(tiers);
        };
    }

    /** Company name, matched against the normalized form the pipeline computes. */
    public static Specification<Job> company(String company) {
        return (root, q, cb) -> {
            if (company == null || company.isBlank()) return null;
            return cb.like(cb.lower(root.get("companyNorm")),
                    "%" + company.toLowerCase(Locale.ROOT) + "%");
        };
    }

    /**
     * Seniority.
     *
     * <p>There is no seniority column — the pipeline stores a {@code category}
     * ({@code intern}/{@code newgrad}) plus a free-text title. So INTERN and
     * NEW_GRAD map to the indexed category column, while SENIOR is inferred
     * from title keywords and is genuinely approximate: these feeds are
     * intern/new-grad focused, so a SENIOR filter returns very little and what
     * it does return is a heuristic, not a classification.
     */
    public static Specification<Job> seniority(Seniority seniority) {
        return (root, q, cb) -> {
            if (seniority == null) return null;
            return switch (seniority) {
                case INTERN -> cb.equal(root.get("category"), "intern");
                case NEW_GRAD -> cb.equal(root.get("category"), "newgrad");
                case SENIOR -> cb.or(
                        cb.like(cb.lower(root.get("titleNorm")), "%senior%"),
                        cb.like(cb.lower(root.get("titleNorm")), "%staff%"),
                        cb.like(cb.lower(root.get("titleNorm")), "%principal%"));
            };
        };
    }

    /**
     * Skill keyword, matched against title and the terms array.
     *
     * <p>Also a substring scan. This is lexical matching, not semantic — a
     * search for "distributed systems" will not find "microservices". Vector
     * search for that case lives in the Python service behind pgvector; naming
     * this one "skill filter" rather than "AI matching" is deliberate.
     */
    public static Specification<Job> skill(String skill) {
        return (root, q, cb) -> {
            if (skill == null || skill.isBlank()) return null;
            String needle = "%" + skill.toLowerCase(Locale.ROOT) + "%";
            return cb.or(
                    cb.like(cb.lower(root.get("titleNorm")), needle),
                    cb.like(cb.lower(root.get("terms")), needle));
        };
    }

    /** Combine every supplied filter with AND. Null specs are ignored. */
    public static Specification<Job> from(SearchQuery query) {
        return Specification.where(active())
                .and(location(query.location()))
                .and(sponsorTier(query.tier()))
                .and(company(query.company()))
                .and(seniority(query.seniority()))
                .and(skill(query.skill()));
    }

    public enum Seniority {
        INTERN, NEW_GRAD, SENIOR
    }
}
