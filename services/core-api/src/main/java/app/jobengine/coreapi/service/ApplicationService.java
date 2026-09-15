package app.jobengine.coreapi.service;

import app.jobengine.coreapi.web.ApplicationRequests;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/** Transactional, user-scoped application tracking over the shared schema. */
@Service
public class ApplicationService {
    private final JdbcClient jdbc;

    public ApplicationService(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public List<Map<String, Object>> list(int userId) {
        return jdbc.sql("""
                SELECT app_id, dedup_key, company, title, source, status,
                       applied_date, last_update, url, notes, contact_email
                FROM applications WHERE user_id = :userId
                ORDER BY last_update DESC
                """).param("userId", userId).query(this::row).list();
    }

    @Transactional
    public Map<String, Object> create(int userId, ApplicationRequests.Create request) {
        String now = Instant.now().toString();
        Integer id = jdbc.sql("""
                INSERT INTO applications
                  (user_id, dedup_key, company, title, source, status,
                   applied_date, last_update, url, notes, contact_email)
                VALUES (:userId, :dedupKey, :company, :title, :source, 'applied',
                        :now, :now, :url, :notes, :contactEmail)
                RETURNING app_id
                """)
                .param("userId", userId).param("dedupKey", request.dedupKey())
                .param("company", request.company().trim()).param("title", request.title().trim())
                .param("source", request.source().trim()).param("now", now)
                .param("url", value(request.url())).param("notes", value(request.notes()))
                .param("contactEmail", value(request.contactEmail()))
                .query(Integer.class).single();
        addEvent(id, "applied", "created", now);
        return findOwned(id, userId);
    }

    @Transactional
    public Map<String, Object> updateStatus(int appId, int userId,
                                             ApplicationRequests.StatusChange request) {
        String now = Instant.now().toString();
        int changed = jdbc.sql("""
                UPDATE applications SET status = :status, last_update = :now
                WHERE app_id = :appId AND user_id = :userId
                """).param("status", request.status()).param("now", now)
                .param("appId", appId).param("userId", userId).update();
        if (changed == 0) notFound();
        addEvent(appId, request.status(), value(request.note()), now);
        return findOwned(appId, userId);
    }

    @Transactional
    public void delete(int appId, int userId) {
        int changed = jdbc.sql("DELETE FROM applications WHERE app_id=:id AND user_id=:user")
                .param("id", appId).param("user", userId).update();
        if (changed == 0) notFound();
    }

    private Map<String, Object> findOwned(int appId, int userId) {
        return jdbc.sql("""
                SELECT app_id, dedup_key, company, title, source, status,
                       applied_date, last_update, url, notes, contact_email
                FROM applications WHERE app_id=:id AND user_id=:user
                """).param("id", appId).param("user", userId).query(this::row).optional()
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "application not found"));
    }

    private void addEvent(int appId, String status, String note, String now) {
        jdbc.sql("""
                INSERT INTO status_events (app_id, status, note, occurred_at)
                VALUES (:id, :status, :note, :now)
                """).param("id", appId).param("status", status)
                .param("note", note).param("now", now).update();
    }

    private Map<String, Object> row(ResultSet rs, int ignored) throws SQLException {
        return Map.ofEntries(
                Map.entry("appId", rs.getInt("app_id")),
                Map.entry("dedupKey", value(rs.getString("dedup_key"))),
                Map.entry("company", rs.getString("company")),
                Map.entry("title", rs.getString("title")),
                Map.entry("source", rs.getString("source")),
                Map.entry("status", rs.getString("status")),
                Map.entry("appliedDate", rs.getString("applied_date")),
                Map.entry("lastUpdate", rs.getString("last_update")),
                Map.entry("url", value(rs.getString("url"))),
                Map.entry("notes", value(rs.getString("notes"))),
                Map.entry("contactEmail", value(rs.getString("contact_email"))));
    }

    private static String value(String input) { return input == null ? "" : input; }
    private static void notFound() {
        throw new ResponseStatusException(HttpStatus.NOT_FOUND, "application not found");
    }
}
