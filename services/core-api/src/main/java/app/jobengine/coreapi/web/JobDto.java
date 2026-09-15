package app.jobengine.coreapi.web;

import app.jobengine.coreapi.domain.Job;

import java.io.Serializable;
import java.util.List;

/**
 * Wire representation of a job.
 *
 * <p>A separate type from the {@link Job} entity on purpose. Serializing
 * entities directly couples the public API to the database schema — a column
 * rename becomes a breaking API change, and lazy-loaded associations serialize
 * into surprises. It also lets the JSON-encoded {@code locations} and
 * {@code terms} columns be decoded into real arrays here, so clients don't each
 * write their own parser.
 *
 * <p>{@link Serializable} because these are what actually sit in the Redis
 * cache.
 */
public record JobDto(
        String dedupKey,
        String company,
        String title,
        String category,
        List<String> locations,
        List<String> terms,
        String url,
        String sponsorTier,
        Integer sponsorLcaCount,
        String sponsorMatch,
        Long datePosted
) implements Serializable {

    public static JobDto from(Job job, JsonArrayCodec codec) {
        return new JobDto(
                job.getDedupKey(),
                job.getCompany(),
                job.getTitle(),
                job.getCategory(),
                codec.decode(job.getLocations()),
                codec.decode(job.getTerms()),
                job.getUrl(),
                job.getSponsorTier(),
                job.getSponsorLcaCount(),
                job.getSponsorMatch(),
                job.getDatePosted());
    }
}
