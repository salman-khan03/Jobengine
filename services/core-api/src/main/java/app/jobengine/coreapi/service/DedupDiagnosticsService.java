package app.jobengine.coreapi.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/** Read-only diagnostics around the Python-owned deduplication decision. */
@Service
public class DedupDiagnosticsService {
    private final JdbcClient jdbc;

    public DedupDiagnosticsService(JdbcClient jdbc) { this.jdbc = jdbc; }

    public List<Map<String, Object>> canonicalUrlConflicts(int limit) {
        return jdbc.sql("""
                SELECT url_canon, count(*) AS row_count,
                       array_agg(DISTINCT company) AS companies,
                       array_agg(DISTINCT title) AS titles
                FROM jobs
                WHERE url_canon IS NOT NULL AND url_canon <> ''
                GROUP BY url_canon HAVING count(*) > 1
                ORDER BY count(*) DESC, url_canon
                LIMIT :limit
                """).param("limit", Math.max(1, Math.min(limit, 200)))
                .query((rs, ignored) -> Map.of(
                        "canonicalUrl", rs.getString("url_canon"),
                        "rowCount", rs.getInt("row_count"),
                        "companies", List.of((String[]) rs.getArray("companies").getArray()),
                        "titles", List.of((String[]) rs.getArray("titles").getArray())))
                .list();
    }
}
