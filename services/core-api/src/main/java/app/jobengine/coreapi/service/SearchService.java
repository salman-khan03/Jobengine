package app.jobengine.coreapi.service;

import app.jobengine.coreapi.domain.Job;
import app.jobengine.coreapi.repo.JobRepository;
import app.jobengine.coreapi.repo.JobSpecifications;
import app.jobengine.coreapi.web.JobDto;
import app.jobengine.coreapi.web.JsonArrayCodec;
import app.jobengine.coreapi.web.SearchQuery;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Job search with a Redis read-through cache.
 *
 * <p><b>Why the cache is managed manually instead of with {@code @Cacheable}.</b>
 * The annotation is cleaner, but it gives no way to observe whether a call was
 * a hit or a miss — the proxy handles it before your code runs. Cache hit rate
 * is one of the metrics this project needs to report honestly, and a hit rate
 * you cannot measure is a hit rate you are guessing at. Doing the lookup
 * explicitly costs about ten lines and makes the number real.
 *
 * <p><b>Why caching search at all.</b> The jobs table is rebuilt a few times a
 * day and read constantly, and the filter space has a heavy head: most traffic
 * is a handful of popular combinations (new grad + strong sponsor + remote).
 * That is close to the ideal cache profile — high repeat rate, cheap
 * invalidation, and staleness bounded by a TTL shorter than the refresh
 * interval, so a cached result can never be older than the data itself.
 */
@Service
public class SearchService {

    private static final Logger log = LoggerFactory.getLogger(SearchService.class);
    public static final String CACHE_NAME = "jobSearch";

    private final JobRepository jobs;
    private final CacheManager cacheManager;
    private final JsonArrayCodec codec;
    private final Counter hits;
    private final Counter misses;
    private final Timer searchTimer;

    public SearchService(JobRepository jobs, CacheManager cacheManager,
                         JsonArrayCodec codec, MeterRegistry metrics) {
        this.jobs = jobs;
        this.cacheManager = cacheManager;
        this.codec = codec;
        this.hits = Counter.builder("jobengine.search.cache")
                .tag("result", "hit")
                .description("Search requests served from Redis")
                .register(metrics);
        this.misses = Counter.builder("jobengine.search.cache")
                .tag("result", "miss")
                .description("Search requests that reached PostgreSQL")
                .register(metrics);
        this.searchTimer = Timer.builder("jobengine.search.latency")
                .description("End-to-end search latency, cache and database paths combined")
                .publishPercentiles(0.5, 0.95, 0.99)
                .register(metrics);
    }

    @SuppressWarnings("unchecked")
    public List<JobDto> search(SearchQuery rawQuery) {
        // Canonicalize first: ?tier=strong,moderate and ?tier=moderate,strong
        // must be the same cache entry, or the hit rate is destroyed by
        // trivial spelling differences.
        SearchQuery query = rawQuery.normalized();

        return searchTimer.record(() -> {
            Cache cache = cacheManager.getCache(CACHE_NAME);
            if (cache != null) {
                Cache.ValueWrapper cached = cache.get(query);
                if (cached != null) {
                    hits.increment();
                    return (List<JobDto>) cached.get();
                }
            }
            misses.increment();

            List<JobDto> results = queryDatabase(query);

            if (cache != null) {
                // Cache even empty results. A filter combination that matches
                // nothing is otherwise a permanent miss, and "no results" is a
                // common query shape when someone over-filters.
                cache.put(query, results);
            }
            return results;
        });
    }

    private List<JobDto> queryDatabase(SearchQuery query) {
        var page = PageRequest.of(
                query.offset() / query.limit(),
                query.limit(),
                // Newest first. Sorting in the database rather than in Java so
                // the LIMIT actually limits work instead of fetching everything
                // and discarding it after sorting.
                Sort.by(Sort.Direction.DESC, "datePosted"));

        List<Job> rows = jobs.findAll(JobSpecifications.from(query), page).getContent();
        log.debug("search miss: {} filters matched {} rows", query, rows.size());
        return rows.stream().map(job -> JobDto.from(job, codec)).toList();
    }

    /** Drop cached searches. Called by the pipeline after a data refresh. */
    public void invalidate() {
        Cache cache = cacheManager.getCache(CACHE_NAME);
        if (cache != null) {
            cache.clear();
            log.info("search cache invalidated");
        }
    }
}
