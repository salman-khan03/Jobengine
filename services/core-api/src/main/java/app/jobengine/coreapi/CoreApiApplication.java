package app.jobengine.coreapi;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;

/**
 * JobEngine Core API — the online serving tier.
 *
 * <p>This service owns <em>reads and user writes</em>: job search with filters,
 * match scoring, and the application tracker. It deliberately does <em>not</em>
 * own ingestion. The Python pipeline (fetch → normalize → dedup → sponsor
 * annotate → upsert) remains the only writer to the {@code jobs} table.
 *
 * <p>Why the split runs along that line: deduplication depends on
 * {@code normalize.py}'s company/title/URL canonicalization, which is tuned
 * against real messy data and covered by tests. Reimplementing it in Java would
 * create two normalizers that must agree forever — the classic way a polyglot
 * system develops a silent correctness bug. So Java serves deduplicated data
 * and reports dedup statistics; Python decides what "duplicate" means.
 */
@SpringBootApplication
@EnableCaching
public class CoreApiApplication {
    public static void main(String[] args) {
        SpringApplication.run(CoreApiApplication.class, args);
    }
}
