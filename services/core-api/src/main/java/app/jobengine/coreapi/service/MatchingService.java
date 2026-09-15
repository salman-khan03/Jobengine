package app.jobengine.coreapi.service;

import app.jobengine.coreapi.domain.Job;
import app.jobengine.coreapi.repo.JobRepository;
import io.micrometer.core.instrument.Timer;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Explainable lexical matching: every point is backed by an evidence token. */
@Service
public class MatchingService {
    private static final Pattern WORD = Pattern.compile("[a-z][a-z0-9+#.]{1,}");
    private static final Set<String> STOP = Set.of(
            "the", "and", "for", "with", "you", "our", "are", "will", "this",
            "that", "have", "your", "job", "role", "team", "work", "experience",
            "skills", "required", "preferred", "company", "position");

    private final JobRepository jobs;
    private final Timer timer;

    public MatchingService(JobRepository jobs, io.micrometer.core.instrument.MeterRegistry metrics) {
        this.jobs = jobs;
        this.timer = Timer.builder("jobengine.match.latency")
                .description("Time to score one profile against one listing")
                .publishPercentiles(0.5, 0.95, 0.99).register(metrics);
    }

    public Map<String, Object> match(String dedupKey, String profileText) {
        return timer.record(() -> {
            Job job = jobs.findById(dedupKey).orElseThrow(() ->
                    new ResponseStatusException(HttpStatus.NOT_FOUND, "job not found"));
            Set<String> target = tokens(String.join(" ",
                    value(job.getTitle()), value(job.getCategory()), value(job.getTerms())));
            Set<String> profile = tokens(profileText);
            List<String> matched = target.stream().filter(profile::contains).sorted().toList();
            List<String> missing = target.stream().filter(token -> !profile.contains(token))
                    .sorted().limit(20).toList();
            double score = target.isEmpty() ? 0 : (100.0 * matched.size() / target.size());
            return Map.of(
                    "dedupKey", dedupKey,
                    "score", Math.round(score * 10.0) / 10.0,
                    "matchedTerms", matched,
                    "missingTerms", missing,
                    "method", "lexical-overlap-v1");
        });
    }

    public static Set<String> tokens(String text) {
        Set<String> result = new HashSet<>();
        Matcher matcher = WORD.matcher(value(text).toLowerCase(Locale.ROOT));
        while (matcher.find()) {
            if (!STOP.contains(matcher.group())) result.add(matcher.group());
        }
        return result;
    }

    private static String value(String value) { return value == null ? "" : value; }
}
