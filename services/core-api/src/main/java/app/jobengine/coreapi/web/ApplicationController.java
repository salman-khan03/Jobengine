package app.jobengine.coreapi.web;

import app.jobengine.coreapi.config.JwtUserResolver;
import app.jobengine.coreapi.service.ApplicationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/applications")
@Tag(name = "Applications", description = "JWT-authenticated, per-user application tracking")
public class ApplicationController {
    private final ApplicationService applications;
    private final JwtUserResolver users;

    public ApplicationController(ApplicationService applications, JwtUserResolver users) {
        this.applications = applications;
        this.users = users;
    }

    @GetMapping
    public List<Map<String, Object>> list(HttpServletRequest request) {
        return applications.list(users.requireUserId(request));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    @Operation(summary = "Track an application")
    public Map<String, Object> create(@Valid @RequestBody ApplicationRequests.Create body,
                                      HttpServletRequest request) {
        return applications.create(users.requireUserId(request), body);
    }

    @PostMapping("/{appId}/status")
    public Map<String, Object> updateStatus(@PathVariable int appId,
            @Valid @RequestBody ApplicationRequests.StatusChange body,
            HttpServletRequest request) {
        return applications.updateStatus(appId, users.requireUserId(request), body);
    }

    @DeleteMapping("/{appId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable int appId, HttpServletRequest request) {
        applications.delete(appId, users.requireUserId(request));
    }
}
