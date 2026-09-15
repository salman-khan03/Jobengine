package app.jobengine.coreapi.web;

import app.jobengine.coreapi.repo.JobSpecifications.Seniority;
import io.swagger.v3.oas.annotations.media.Schema;

import java.io.Serializable;
import java.util.List;
import java.util.Locale;

/**
 * A search request.
 *
 * <p>A record, and {@link Serializable}, because it doubles as the Redis cache
 * key. Records give a correct {@code equals}/{@code hashCode} over every
 * component for free — which is exactly the property a cache key needs, and
 * exactly the thing that silently breaks when someone adds a field to a
 * hand-written key class and forgets to update {@code hashCode}.
 *
 * @param location one or more location substrings, OR-ed together
 * @param tier     sponsorship tiers to include
 * @param company  company name substring
 * @param seniority intern / new grad / senior
 * @param skill    keyword matched against title and terms
 * @param limit    page size, clamped by {@link #normalized()}
 * @param offset   page offset
 */
public record SearchQuery(
        @Schema(description = "Location substrings, OR-ed", example = "[\"Remote\",\"Seattle\"]")
        List<String> location,

        @Schema(description = "Sponsorship tiers", example = "[\"strong\",\"moderate\"]")
        List<String> tier,

        @Schema(description = "Company name substring", example = "stripe")
        String company,

        @Schema(description = "Seniority band")
        Seniority seniority,

        @Schema(description = "Skill keyword matched against title and terms", example = "kubernetes")
        String skill,

        @Schema(description = "Page size (1-200)", defaultValue = "50")
        Integer limit,

        @Schema(description = "Page offset", defaultValue = "0")
        Integer offset
) implements Serializable {

    public static final int MAX_LIMIT = 200;
    public static final int DEFAULT_LIMIT = 50;

    /**
     * Clamp and canonicalize before the value is used as a cache key.
     *
     * <p>Two reasons this matters. Clamping {@code limit} stops a single
     * {@code ?limit=100000} request from holding a connection while it
     * materializes the whole table — the unbounded-{@code max} problem the
     * Python API still has. Canonicalizing (lowercase, trimmed, nulls folded)
     * means {@code ?company=Stripe} and {@code ?company=stripe%20} hit the same
     * cache entry instead of two, which is most of the difference between a
     * useful cache hit rate and a useless one.
     */
    public SearchQuery normalized() {
        return new SearchQuery(
                normalizeList(location),
                normalizeList(tier),
                blankToNull(company),
                seniority,
                blankToNull(skill),
                limit == null ? DEFAULT_LIMIT : Math.clamp(limit, 1, MAX_LIMIT),
                offset == null ? 0 : Math.max(0, offset));
    }

    private static List<String> normalizeList(List<String> values) {
        if (values == null) return null;
        List<String> cleaned = values.stream()
                .filter(v -> v != null && !v.isBlank())
                .map(v -> v.trim().toLowerCase(Locale.ROOT))
                .distinct()
                .sorted() // order must not create a distinct cache key
                .toList();
        return cleaned.isEmpty() ? null : cleaned;
    }

    private static String blankToNull(String value) {
        if (value == null || value.isBlank()) return null;
        return value.trim().toLowerCase(Locale.ROOT);
    }
}
