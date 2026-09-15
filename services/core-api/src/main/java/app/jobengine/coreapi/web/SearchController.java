package app.jobengine.coreapi.web;

import app.jobengine.coreapi.repo.JobRepository;
import app.jobengine.coreapi.repo.JobSpecifications.Seniority;
import app.jobengine.coreapi.service.SearchService;
import app.jobengine.coreapi.service.MatchingService;
import app.jobengine.coreapi.service.DedupDiagnosticsService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import jakarta.validation.Valid;

import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;

@RestController
@RequestMapping("/api/v1/jobs")
@Tag(name = "Search", description = "Sponsor-aware job search over deduplicated listings")
public class SearchController {

    private final SearchService search;
    private final JobRepository jobs;
    private final MatchingService matching;
    private final DedupDiagnosticsService dedupDiagnostics;

    public SearchController(SearchService search, JobRepository jobs,
                            MatchingService matching,
                            DedupDiagnosticsService dedupDiagnostics) {
        this.search = search;
        this.jobs = jobs;
        this.matching = matching;
        this.dedupDiagnostics = dedupDiagnostics;
    }

    @GetMapping
    @Operation(
            summary = "Search job listings",
            description = """
                    Filters are independent and combine with AND; list-valued
                    filters (location, tier) combine with OR internally.

                    Results are cached in Redis for a TTL shorter than the data
                    refresh interval, so a cached result is never staler than
                    the underlying data. Filter values are canonicalized before
                    caching, so ?tier=strong,moderate and ?tier=moderate,strong
                    are the same cache entry.
                    """)
    public List<JobDto> search(
            @Parameter(description = "Location substrings, OR-ed together")
            @RequestParam(required = false) List<String> location,

            @Parameter(description = "Sponsorship tiers from DOL H-1B LCA history")
            @RequestParam(required = false) List<String> tier,

            @Parameter(description = "Company name substring")
            @RequestParam(required = false) String company,

            @Parameter(description = "Seniority band")
            @RequestParam(required = false) Seniority seniority,

            @Parameter(description = "Skill keyword, matched against title and terms")
            @RequestParam(required = false) String skill,

            @Parameter(description = "Page size, clamped to 200")
            @RequestParam(required = false) Integer limit,

            @Parameter(description = "Page offset")
            @RequestParam(required = false) Integer offset) {

        return search.search(
                new SearchQuery(location, tier, company, seniority, skill, limit, offset));
    }

    @GetMapping("/stats")
    @Operation(
            summary = "Corpus and deduplication statistics",
            description = """
                    Measured against what is actually stored, not reported from
                    ingest logs. `duplicateRatio` is the share of rows that
                    share a canonical URL with another row — a non-zero value
                    means the dedup key and the canonical URL disagree, which is
                    the signal that normalization needs attention.
                    """)
    public Map<String, Object> stats() {
        long total = jobs.count();
        long active = jobs.countActive();
        long distinctUrls = jobs.countDistinctCanonicalUrls();
        double duplicateRatio = total == 0 ? 0.0 : 1.0 - ((double) distinctUrls / total);

        return Map.of(
                "totalListings", total,
                "activeListings", active,
                "distinctCanonicalUrls", distinctUrls,
                "duplicateRatio", Math.round(duplicateRatio * 10_000) / 10_000.0);
    }

    @GetMapping("/tiers")
    @Operation(summary = "Count active listings by sponsorship tier")
    public Map<String, Long> tiers() {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (Object[] row : jobs.countActiveBySponsorTier()) {
            counts.put(String.valueOf(row[0]), (Long) row[1]);
        }
        return counts;
    }

    @GetMapping("/dedup-conflicts")
    @Operation(summary = "Inspect canonical-URL conflicts",
            description = "Returns rows the offline deduplicator may have failed to merge. Read-only: Python remains the sole normalization writer.")
    public List<Map<String, Object>> dedupConflicts(
            @RequestParam(defaultValue = "50") int limit) {
        return dedupDiagnostics.canonicalUrlConflicts(limit);
    }

    @PostMapping("/match")
    @Operation(summary = "Explain a profile-to-job match",
            description = "Transparent lexical overlap with matched and missing evidence terms; no opaque AI score.")
    public Map<String, Object> match(@Valid @RequestBody MatchRequest body) {
        return matching.match(body.dedupKey(), body.profileText());
    }
}
