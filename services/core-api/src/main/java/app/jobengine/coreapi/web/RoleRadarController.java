package app.jobengine.coreapi.web;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/** Public v2 boundary; Python owns evidence extraction, ranking and user authorization. */
@RestController
@RequestMapping("/api/v2")
public class RoleRadarController {
    private final URI worker;
    private final Duration timeout;
    private final HttpClient client;

    public RoleRadarController(
            @Value("${jobengine.roleradar.worker-url:http://localhost:8765}") String workerUrl,
            @Value("${jobengine.roleradar.timeout:30s}") Duration timeout) {
        this.worker = URI.create(workerUrl);
        if (!java.util.Set.of("http", "https").contains(worker.getScheme())
                || worker.getHost() == null || worker.getUserInfo() != null
                || worker.getQuery() != null || worker.getFragment() != null
                || !(worker.getPath().isEmpty() || worker.getPath().equals("/"))) {
            throw new IllegalArgumentException("RoleRadar worker URL must be an HTTP(S) origin");
        }
        if (timeout.isNegative() || timeout.isZero() || timeout.compareTo(Duration.ofSeconds(120)) > 0) {
            throw new IllegalArgumentException("RoleRadar timeout must be positive and at most 120 seconds");
        }
        this.timeout = timeout;
        this.client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    // Explicit mappings prevent this API from becoming an arbitrary worker proxy.
    @GetMapping({"/profile", "/evidence", "/decisions", "/outcomes/funnel", "/evaluation", "/taxonomy", "/model"})
    public ResponseEntity<byte[]> get(HttpServletRequest request) {
        return forward(request, null);
    }

    @PostMapping(value = {"/profile", "/decide", "/rank", "/outcomes"}, consumes = "application/json")
    public ResponseEntity<byte[]> post(HttpServletRequest request, @RequestBody byte[] body) {
        return forward(request, body);
    }

    private ResponseEntity<byte[]> forward(HttpServletRequest request, byte[] body) {
        String path = request.getRequestURI().substring(request.getContextPath().length());
        String query = request.getQueryString();
        URI target = worker.resolve(path + (query == null ? "" : "?" + query));
        var outbound = HttpRequest.newBuilder(target).timeout(timeout)
                .header(HttpHeaders.ACCEPT, "application/json");
        String authorization = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (authorization != null) {
            outbound.header(HttpHeaders.AUTHORIZATION, authorization);
        }
        if (body == null) {
            outbound.GET();
        } else {
            outbound.header(HttpHeaders.CONTENT_TYPE, "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body));
        }
        try {
            var response = client.send(outbound.build(), HttpResponse.BodyHandlers.ofByteArray());
            var headers = privateHeaders();
            response.headers().firstValue(HttpHeaders.CONTENT_TYPE)
                    .ifPresent(value -> headers.set(HttpHeaders.CONTENT_TYPE, value));
            response.headers().firstValue(HttpHeaders.WWW_AUTHENTICATE)
                    .ifPresent(value -> headers.set(HttpHeaders.WWW_AUTHENTICATE, value));
            response.headers().firstValue(HttpHeaders.RETRY_AFTER)
                    .ifPresent(value -> headers.set(HttpHeaders.RETRY_AFTER, value));
            return ResponseEntity.status(response.statusCode()).headers(headers).body(response.body());
        } catch (HttpTimeoutException exception) {
            return unavailable(504, "decision worker timed out");
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            return unavailable(503, "decision request interrupted");
        } catch (IOException exception) {
            return unavailable(503, "decision worker unavailable");
        }
    }

    private static HttpHeaders privateHeaders() {
        var headers = new HttpHeaders();
        headers.setCacheControl("no-store");
        return headers;
    }

    private static ResponseEntity<byte[]> unavailable(int status, String detail) {
        var headers = privateHeaders();
        headers.set(HttpHeaders.CONTENT_TYPE, "application/json");
        return ResponseEntity.status(status).headers(headers)
                .body(("{\"detail\":\"" + detail + "\"}").getBytes(StandardCharsets.UTF_8));
    }
}
