package app.jobengine.coreapi;

import app.jobengine.coreapi.service.MatchingService;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class MatchingServiceTest {
    @Test
    void tokenizationIsCaseInsensitiveAndRemovesBoilerplate() {
        assertThat(MatchingService.tokens("Java JAVA and distributed-systems experience"))
                .containsExactlyInAnyOrder("java", "distributed", "systems");
    }
}
