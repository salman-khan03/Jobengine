package app.jobengine.coreapi.config;

import app.jobengine.coreapi.service.SearchService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.time.Duration;
import java.util.Map;

/**
 * Redis cache wiring.
 *
 * <p>The TTL is the important decision here, and it is deliberately shorter
 * than the data refresh interval. The pipeline runs roughly every 6 hours; a
 * 10-minute TTL means a cached search can never be meaningfully staler than the
 * underlying data, and it bounds the damage if a cache invalidation is ever
 * missed. Cache invalidation on refresh is the primary mechanism; the TTL is
 * the safety net, not the plan.
 *
 * <p>Null values are not cached — {@code disableCachingNullValues} — because a
 * null here would mean a bug, and caching it would make that bug sticky.
 */
@Configuration
@ConfigurationProperties(prefix = "jobengine.cache")
// Without this condition, defining `cacheManager` explicitly overrides Spring's
// auto-configuration and `spring.cache.type=none` silently does nothing — the
// cache stays on no matter what the property says. Found by measurement: a
// benchmark run with caching supposedly disabled still reported a 99.99% hit
// rate. Gating the bean restores the standard off-switch, which is what makes
// the cached-vs-uncached comparison possible at all.
@ConditionalOnProperty(name = "spring.cache.type", havingValue = "redis", matchIfMissing = true)
public class RedisCacheConfig {

    private Duration searchTtl = Duration.ofMinutes(10);

    @Bean
    public RedisCacheManager cacheManager(RedisConnectionFactory connectionFactory) {
        RedisCacheConfiguration defaults = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(searchTtl)
                .disableCachingNullValues()
                .computePrefixWith(name -> "jobengine:" + name + ":")
                .serializeKeysWith(RedisSerializationContext.SerializationPair
                        .fromSerializer(new StringRedisSerializer()));

        return RedisCacheManager.builder(connectionFactory)
                .cacheDefaults(defaults)
                .withInitialCacheConfigurations(Map.of(
                        SearchService.CACHE_NAME, defaults))
                // If Redis is down, a cache miss must not become a failed
                // request. Spring's default here throws; transaction-aware
                // building plus the fail-open handler in CacheErrorConfig means
                // the service degrades to database-only instead of erroring.
                .transactionAware()
                .build();
    }

    public Duration getSearchTtl() {
        return searchTtl;
    }

    public void setSearchTtl(Duration searchTtl) {
        this.searchTtl = searchTtl;
    }
}
