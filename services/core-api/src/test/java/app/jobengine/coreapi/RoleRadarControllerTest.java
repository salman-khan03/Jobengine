package app.jobengine.coreapi;

import app.jobengine.coreapi.web.RoleRadarController;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class RoleRadarControllerTest {
    private HttpServer worker;
    private MockMvc mvc;
    private final AtomicReference<String> authorization = new AtomicReference<>();
    private final AtomicReference<String> receivedBody = new AtomicReference<>();
    private final AtomicReference<String> receivedUri = new AtomicReference<>();

    @BeforeEach
    void startWorker() throws Exception {
        worker = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        worker.createContext("/api/v2", exchange -> {
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            receivedBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            receivedUri.set(exchange.getRequestURI().toString());
            byte[] payload = "{\"detail\":\"sign in required\"}".getBytes(StandardCharsets.UTF_8);
            boolean authenticated = "Bearer test-token".equals(authorization.get());
            if (authenticated) payload = "{\"decision\":\"apply\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.getResponseHeaders().set("Cache-Control", "public, max-age=999");
            exchange.sendResponseHeaders(authenticated ? 200 : 401, payload.length);
            exchange.getResponseBody().write(payload);
            exchange.close();
        });
        worker.start();
        mvc = MockMvcBuilders.standaloneSetup(new RoleRadarController(origin(), Duration.ofSeconds(2))).build();
    }

    private String origin() {
        return "http://127.0.0.1:" + worker.getAddress().getPort();
    }

    @AfterEach
    void stopWorker() {
        worker.stop(0);
    }

    @Test
    void forwardsBearerAndJsonWithoutAllowingWorkerToCachePersonalData() throws Exception {
        String body = "{\"resume\":{\"name\":\"A Candidate\"},\"save\":true}";
        mvc.perform(post("/api/v2/decide").contentType("application/json")
                        .header("Authorization", "Bearer test-token").content(body))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"decision\":\"apply\"}"))
                .andExpect(header().string("Cache-Control", "no-store"));
        assertThat(receivedBody.get()).isEqualTo(body);
        assertThat(authorization.get()).isEqualTo("Bearer test-token");
        assertThat(receivedUri.get()).isEqualTo("/api/v2/decide");
    }

    @Test
    void preservesAuthenticationFailureAndQueryString() throws Exception {
        mvc.perform(get("/api/v2/decisions?limit=10&offset=2"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"detail\":\"sign in required\"}"))
                .andExpect(header().string("Cache-Control", "no-store"));
        assertThat(receivedUri.get()).isEqualTo("/api/v2/decisions?limit=10&offset=2");
    }

    @Test
    void rejectsUnsupportedRoutesAndMethodsWithoutCallingWorker() throws Exception {
        mvc.perform(get("/api/v2/admin")).andExpect(status().isNotFound());
        mvc.perform(get("/api/v2/decide")).andExpect(status().isMethodNotAllowed());
        assertThat(receivedUri.get()).isNull();
    }

    @Test
    void unavailableWorkerReturnsSanitized503() throws Exception {
        worker.stop(0);
        mvc.perform(get("/api/v2/model"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(content().json("{\"detail\":\"decision worker unavailable\"}"))
                .andExpect(header().string("Cache-Control", "no-store"));
    }

    @Test
    void slowWorkerReturns504WithinConfiguredDeadlineWithoutExposingWorkerDetails() throws Exception {
        worker.createContext("/api/v2/model", exchange -> {
            try {
                Thread.sleep(500);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            } finally {
                exchange.close();
            }
        });
        mvc = MockMvcBuilders.standaloneSetup(
                new RoleRadarController(origin(), Duration.ofMillis(100))).build();
        mvc.perform(get("/api/v2/model"))
                .andExpect(status().isGatewayTimeout())
                .andExpect(content().json("{\"detail\":\"decision worker timed out\"}"))
                .andExpect(header().string("Cache-Control", "no-store"));
    }

    @Test
    void refusesUnsafeOrUnboundedConfiguration() {
        assertThatThrownBy(() -> new RoleRadarController("file:///tmp", Duration.ofSeconds(1)))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new RoleRadarController(origin(), Duration.ofMinutes(3)))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
