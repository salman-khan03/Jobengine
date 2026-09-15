package app.jobengine.coreapi.web;

import jakarta.validation.constraints.NotBlank;

public record MatchRequest(@NotBlank String dedupKey, @NotBlank String profileText) {}
