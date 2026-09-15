package app.jobengine.coreapi.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class RoleRadarCorsConfig implements WebMvcConfigurer {
    private final String[] origins;

    public RoleRadarCorsConfig(@Value("${jobengine.roleradar.cors-origins:http://localhost:3000,http://127.0.0.1:3000}") String[] origins) {
        this.origins = origins;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/v2/**").allowedOrigins(origins)
                .allowedMethods("GET", "POST", "OPTIONS")
                .allowedHeaders("Authorization", "Content-Type", "X-API-Key")
                .exposedHeaders("Retry-After").maxAge(600);
    }
}
