package app.jobengine.coreapi.config;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * API-key authentication and token-bucket rate limiting.
 *
 * <p>Token bucket rather than a fixed window, because a fixed window lets a
 * caller send its whole minute's quota in the last second of one window and
 * again in the first second of the next — an instantaneous burst of double the
 * intended rate, right at the boundary. A bucket refills continuously and
 * bounds the burst to its capacity.
 *
 * <p>Limits are per key, with unkeyed callers sharing a per-IP bucket.
 *
 * <p><b>Known limitation:</b> buckets live in this process's memory, so with
 * N instances behind a load balancer the effective limit is N times the
 * configured one. Bucket4j supports a Redis-backed distributed store and Redis
 * is already a dependency here; that is the fix, and it is not done yet. For a
 * single-task deployment the in-memory version is correct, and it is honest
 * about when it stops being correct.
 */
@Component
@Order(1)
public class RateLimitFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RateLimitFilter.class);

    private final ApiKeyProperties properties;
    private final Counter rejected;
    private final Map<String, Bucket> buckets = new ConcurrentHashMap<>();

    public RateLimitFilter(ApiKeyProperties properties, MeterRegistry metrics) {
        this.properties = properties;
        this.rejected = Counter.builder("jobengine.ratelimit.rejected")
                .description("Requests rejected with 429")
                .register(metrics);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        // Health and metrics must stay reachable when a caller is being
        // throttled — otherwise the load balancer's own probes can be rate
        // limited and it will start killing healthy tasks.
        String path = request.getRequestURI();
        return path.startsWith("/actuator")
                || (path.startsWith("/api/v2/")
                    && org.springframework.web.cors.CorsUtils.isPreFlightRequest(request));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {

        String presentedKey = request.getHeader(properties.getHeader());
        ApiKeyProperties.KeyConfig config =
                presentedKey == null ? null : properties.getKeys().get(presentedKey);

        if (presentedKey != null && config == null) {
            // A wrong key is rejected outright. Accepting it as anonymous would
            // silently downgrade an integrator to a lower limit and make the
            // resulting 429s inexplicable to them.
            log.debug("rejected unknown API key");
            reject(response, HttpServletResponse.SC_UNAUTHORIZED, "invalid API key");
            return;
        }
        if (presentedKey == null && !properties.isAllowAnonymous()) {
            reject(response, HttpServletResponse.SC_UNAUTHORIZED,
                    "an API key is required — send " + properties.getHeader());
            return;
        }

        String identity = config != null ? "key:" + presentedKey : "ip:" + clientIp(request);
        int limit = config != null
                ? config.getRequestsPerMinute()
                : properties.getAnonymousRequestsPerMinute();

        Bucket bucket = buckets.computeIfAbsent(identity, k -> Bucket.builder()
                .addLimit(Bandwidth.builder()
                        .capacity(limit)
                        .refillGreedy(limit, Duration.ofMinutes(1))
                        .build())
                .build());

        var probe = bucket.tryConsumeAndReturnRemaining(1);
        // Always advertise the limit, not only on rejection — a client can only
        // back off proactively if it can see how much budget is left.
        response.setHeader("X-RateLimit-Limit", String.valueOf(limit));
        response.setHeader("X-RateLimit-Remaining", String.valueOf(Math.max(0, probe.getRemainingTokens())));

        if (!probe.isConsumed()) {
            long waitSeconds = Math.max(1, probe.getNanosToWaitForRefill() / 1_000_000_000L);
            response.setHeader("Retry-After", String.valueOf(waitSeconds));
            rejected.increment();
            log.debug("rate limited {}", identity);
            reject(response, 429, "rate limit exceeded — retry in " + waitSeconds + "s");
            return;
        }

        if (config != null) {
            request.setAttribute("apiKeyOwner", config.getOwner());
        }
        chain.doFilter(request, response);
    }

    /**
     * Trusts X-Forwarded-For only for its first entry, and only because this
     * runs behind a load balancer that overwrites it. Exposed directly to the
     * internet, this header is caller-controlled and trivially spoofed to
     * bypass per-IP limits.
     */
    private String clientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }

    private void reject(HttpServletResponse response, int status, String detail) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.getWriter().write("{\"detail\":\"" + detail + "\"}");
    }
}
