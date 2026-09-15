package app.jobengine.coreapi.web;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Decodes the JSON-encoded string arrays the Python pipeline stores in TEXT
 * columns ({@code locations}, {@code terms}).
 *
 * <p>Yes, these should be native Postgres arrays or JSONB. They are TEXT
 * because the schema was designed to run identically on SQLite, where neither
 * exists. That constraint is real and documented; this class is where the cost
 * of it is paid. Migrating the columns to JSONB is the fix and it belongs in
 * the pipeline, not here.
 */
@Component
public class JsonArrayCodec {

    private static final Logger log = LoggerFactory.getLogger(JsonArrayCodec.class);
    private static final TypeReference<List<String>> LIST_OF_STRING = new TypeReference<>() {
    };

    private final ObjectMapper mapper;

    public JsonArrayCodec(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * Returns an empty list rather than throwing on malformed input. One bad
     * row from upstream should degrade that row's locations, not fail the
     * whole search response.
     */
    public List<String> decode(String raw) {
        if (raw == null || raw.isBlank()) return List.of();
        try {
            return mapper.readValue(raw, LIST_OF_STRING);
        } catch (Exception e) {
            log.debug("could not decode JSON array column: {}", raw, e);
            return List.of();
        }
    }
}
