package app.jobengine.coreapi.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.Cache;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Fail open when Redis is unavailable.
 *
 * <p>A cache is a latency optimization, not a source of truth. The default
 * behaviour propagates Redis errors to the caller, which converts a degraded
 * cache into a full outage — the service still has a perfectly good database it
 * could have answered from. Every handler below logs and swallows, so losing
 * Redis costs latency and nothing else.
 *
 * <p>The tradeoff being accepted: a silent cache failure is harder to notice.
 * That is why these log at WARN and why cache hit rate is a published metric —
 * a hit rate that drops to zero is the alarm.
 */
@Configuration
public class CacheErrorConfig {

    private static final Logger log = LoggerFactory.getLogger(CacheErrorConfig.class);

    @Bean
    public CacheErrorHandler cacheErrorHandler() {
        return new CacheErrorHandler() {
            @Override
            public void handleCacheGetError(RuntimeException e, Cache cache, Object key) {
                log.warn("cache GET failed on {} — serving from database", cache.getName(), e);
            }

            @Override
            public void handleCachePutError(RuntimeException e, Cache cache, Object key, Object value) {
                log.warn("cache PUT failed on {} — result not cached", cache.getName(), e);
            }

            @Override
            public void handleCacheEvictError(RuntimeException e, Cache cache, Object key) {
                log.warn("cache EVICT failed on {} — entry may be stale until TTL", cache.getName(), e);
            }

            @Override
            public void handleCacheClearError(RuntimeException e, Cache cache) {
                log.warn("cache CLEAR failed on {} — entries expire via TTL", cache.getName(), e);
            }
        };
    }
}
