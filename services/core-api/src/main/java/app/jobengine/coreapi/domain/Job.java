package app.jobengine.coreapi.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A deduplicated job listing.
 *
 * <p>Read-only from this service's perspective — the Python pipeline owns every
 * write. There is deliberately no setter-driven persistence path and no
 * {@code @GeneratedValue}: {@code dedupKey} is a natural key computed at ingest
 * from the normalized company, title, and canonical URL, which is what makes
 * the rebuild idempotent.
 *
 * <p>The schema is defined in {@code src/jobengine/db.py}; this entity maps
 * onto it rather than generating it. {@code ddl-auto} is set to
 * {@code validate} precisely so a drift between the two fails at startup
 * instead of silently at query time.
 */
@Entity
@Table(name = "jobs")
public class Job {

    @Id
    @Column(name = "dedup_key", nullable = false)
    private String dedupKey;

    private String id;

    @Column(name = "source_repo")
    private String sourceRepo;

    private String company;

    @Column(name = "company_norm")
    private String companyNorm;

    private String title;

    @Column(name = "title_norm")
    private String titleNorm;

    private String category;

    /** Stored as an integer flag by the Python pipeline, not a boolean. */
    private Integer active;

    @Column(name = "is_visible")
    private Integer isVisible;

    /** JSON-encoded string array, as written by the pipeline. */
    private String terms;

    @Column(name = "date_posted")
    private Long datePosted;

    @Column(name = "date_updated")
    private Long dateUpdated;

    private String url;

    @Column(name = "url_canon")
    private String urlCanon;

    /** JSON-encoded string array. */
    private String locations;

    @Column(name = "company_url")
    private String companyUrl;

    @Column(name = "sponsorship_simplify")
    private String sponsorshipSimplify;

    private String degrees;

    /** Derived at ingest from DOL LCA filings — see sponsor_index.py. */
    @Column(name = "sponsor_tier")
    private String sponsorTier;

    @Column(name = "sponsor_lca_count")
    private Integer sponsorLcaCount;

    @Column(name = "sponsor_match")
    private String sponsorMatch;

    protected Job() {
        // Required by JPA.
    }

    public String getDedupKey() { return dedupKey; }
    public String getId() { return id; }
    public String getSourceRepo() { return sourceRepo; }
    public String getCompany() { return company; }
    public String getCompanyNorm() { return companyNorm; }
    public String getTitle() { return title; }
    public String getTitleNorm() { return titleNorm; }
    public String getCategory() { return category; }
    public Integer getActive() { return active; }
    public Integer getIsVisible() { return isVisible; }
    public String getTerms() { return terms; }
    public Long getDatePosted() { return datePosted; }
    public Long getDateUpdated() { return dateUpdated; }
    public String getUrl() { return url; }
    public String getUrlCanon() { return urlCanon; }
    public String getLocations() { return locations; }
    public String getCompanyUrl() { return companyUrl; }
    public String getSponsorshipSimplify() { return sponsorshipSimplify; }
    public String getDegrees() { return degrees; }
    public String getSponsorTier() { return sponsorTier; }
    public Integer getSponsorLcaCount() { return sponsorLcaCount; }
    public String getSponsorMatch() { return sponsorMatch; }
}
