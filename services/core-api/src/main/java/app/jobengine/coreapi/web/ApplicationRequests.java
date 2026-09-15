package app.jobengine.coreapi.web;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

public final class ApplicationRequests {
    private ApplicationRequests() {}

    public record Create(
            @NotBlank String company,
            @NotBlank String title,
            @NotBlank String source,
            String dedupKey,
            String url,
            String notes,
            String contactEmail) {}

    public record StatusChange(
            @NotBlank
            @Pattern(regexp = "saved|applied|heard_back|oa|interview|offer|rejected|withdrawn")
            String status,
            String note) {}
}
