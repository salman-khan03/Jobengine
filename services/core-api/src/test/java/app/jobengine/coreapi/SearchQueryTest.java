package app.jobengine.coreapi;

import app.jobengine.coreapi.web.SearchQuery;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SearchQueryTest {

    @Test
    void normalizesEquivalentQueriesToTheSameCacheKey() {
        var left = new SearchQuery(
                List.of(" Remote ", "SEATTLE"),
                List.of("moderate", "Strong"),
                " Stripe ", null, " Java ", 500, -4).normalized();
        var right = new SearchQuery(
                List.of("seattle", "remote"),
                List.of("strong", "moderate"),
                "stripe", null, "java", 200, 0).normalized();

        assertThat(left).isEqualTo(right);
        assertThat(left.limit()).isEqualTo(SearchQuery.MAX_LIMIT);
        assertThat(left.offset()).isZero();
    }

    @Test
    void suppliesSafePaginationDefaults() {
        var query = new SearchQuery(null, null, null, null, null, null, null).normalized();

        assertThat(query.limit()).isEqualTo(SearchQuery.DEFAULT_LIMIT);
        assertThat(query.offset()).isZero();
    }
}
