package app.jobengine.coreapi.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * API key registry and per-tier rate limits.
 *
 * <p>Configuration-driven rather than database-backed, which is the right size
 * for a handful of integrators and honestly the wrong size for more than that:
 * adding a key requires a redeploy, and there is no self-service issuance,
 * rotation, or revocation short of one. That limitation is recorded rather than
 * papered over — moving keys into a table with a hashed secret is the
 * documented next step if anyone actually integrates.
 *
 * <p>Keys are compared against configuration values, so they must be supplied
 * through environment variables in production, never committed. The defaults
 * below exist only so the service starts in development.
 *
 * <pre>
 * jobengine.api-keys.keys.demo-key.owner=demo
 * jobengine.api-keys.keys.demo-key.requests-per-minute=60
 * </pre>
 */
@Component
@ConfigurationProperties(prefix = "jobengine.api-keys")
public class ApiKeyProperties {

    /** Header carrying the key. X-API-Key is the de facto convention. */
    private String header = "X-API-Key";

    /** Requests/minute for callers with no key at all. */
    private int anonymousRequestsPerMinute = 30;

    /** Whether an unkeyed caller may use the public search endpoints. */
    private boolean allowAnonymous = true;

    private Map<String, KeyConfig> keys = new LinkedHashMap<>();

    public static class KeyConfig {
        private String owner = "unknown";
        private int requestsPerMinute = 120;

        public String getOwner() { return owner; }
        public void setOwner(String owner) { this.owner = owner; }
        public int getRequestsPerMinute() { return requestsPerMinute; }
        public void setRequestsPerMinute(int rpm) { this.requestsPerMinute = rpm; }
    }

    public String getHeader() { return header; }
    public void setHeader(String header) { this.header = header; }
    public int getAnonymousRequestsPerMinute() { return anonymousRequestsPerMinute; }
    public void setAnonymousRequestsPerMinute(int v) { this.anonymousRequestsPerMinute = v; }
    public boolean isAllowAnonymous() { return allowAnonymous; }
    public void setAllowAnonymous(boolean v) { this.allowAnonymous = v; }
    public Map<String, KeyConfig> getKeys() { return keys; }
    public void setKeys(Map<String, KeyConfig> keys) { this.keys = keys; }
}
