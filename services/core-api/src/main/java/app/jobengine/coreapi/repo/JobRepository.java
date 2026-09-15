package app.jobengine.coreapi.repo;

import app.jobengine.coreapi.domain.Job;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface JobRepository
        extends JpaRepository<Job, String>, JpaSpecificationExecutor<Job> {

    /**
     * Distinct canonical URLs vs. total rows — the deduplication ratio the
     * pipeline achieved, measured against what is actually stored rather than
     * asserted from ingest logs.
     */
    @Query("select count(distinct j.urlCanon) from Job j")
    long countDistinctCanonicalUrls();

    @Query("select count(j) from Job j where j.active = 1 and j.isVisible = 1")
    long countActive();

    @Query("select j.sponsorTier, count(j) from Job j where j.active = 1 and j.isVisible = 1 group by j.sponsorTier")
    List<Object[]> countActiveBySponsorTier();
}
