package app.jobengine.coreapi;

import app.jobengine.coreapi.config.ApiKeyProperties;
import app.jobengine.coreapi.config.RateLimitFilter;
import app.jobengine.coreapi.config.RoleRadarCorsConfig;
import app.jobengine.coreapi.web.RoleRadarController;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.mock.web.MockServletContext;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;

import java.time.Duration;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class RoleRadarCorsTest {
    @Configuration
    @EnableWebMvc
    static class TestConfiguration {
        @Bean
        RoleRadarController controller() {
            return new RoleRadarController("http://localhost:8765", Duration.ofSeconds(1));
        }

        @Bean
        RoleRadarCorsConfig cors() {
            return new RoleRadarCorsConfig(new String[]{"http://localhost:3000", "http://127.0.0.1:3000"});
        }
    }

    @Test
    void permitsConfiguredBrowserPreflightWithoutApiKeyButRejectsOtherOrigins() throws Exception {
        try (var context = new AnnotationConfigWebApplicationContext()) {
            context.setServletContext(new MockServletContext());
            context.register(TestConfiguration.class);
            context.refresh();
            var properties = new ApiKeyProperties();
            properties.setAllowAnonymous(false);
            var mvc = MockMvcBuilders.webAppContextSetup(context)
                    .addFilters(new RateLimitFilter(properties, new SimpleMeterRegistry())).build();
            mvc.perform(options("/api/v2/decide").header("Origin", "http://localhost:3000")
                            .header("Access-Control-Request-Method", "POST")
                            .header("Access-Control-Request-Headers", "authorization,content-type"))
                    .andExpect(status().isOk())
                    .andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:3000"));
            mvc.perform(options("/api/v2/decide").header("Origin", "https://untrusted.example")
                            .header("Access-Control-Request-Method", "POST"))
                    .andExpect(status().isForbidden())
                    .andExpect(header().doesNotExist("Access-Control-Allow-Origin"));
        }
    }
}
