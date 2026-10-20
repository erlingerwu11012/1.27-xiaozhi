package xiaozhi.modules.personmemory;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.Map;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.*;
import xiaozhi.common.utils.Result;

@RestController
@RequestMapping("/person-memory")
@RequiredArgsConstructor
public class PersonMemoryController {
    private final PersonMemoryService service;
    private final PersonBehaviorService behaviors;
    private final RecentArchiveService recent;
    @Data public static class MaterialRequest {
        @NotNull @Valid private PersonTurnDTO actor;
        @NotBlank @Size(max=128) private String eventId;
        @NotBlank private String kind;
        @NotNull @Size(max=65536) private String content;
    }
    @Data public static class SearchRequest {
        @NotNull @Valid private PersonTurnDTO actor;
        @NotBlank @Size(max=2048) private String query;
    }
    @Data public static class OverrideRequest {
        @NotNull @Valid private PersonTurnDTO actor;
        @NotBlank private String action;
        @NotBlank @Size(max=1024) private String match;
        @Size(max=2048) private String replacement;
    }
    @PostMapping("/internal/material")
    public Result<Void> material(@Valid @RequestBody MaterialRequest request) {
        if("behavior".equals(request.getKind()))behaviors.record(request.getActor(),request.getEventId(),request.getContent());
        else service.material(request.getActor(),request.getEventId(),request.getKind(),request.getContent());return new Result<>();
    }
    @PostMapping("/internal/behavior/prepare")
    public Result<Map<String,Object>> prepare(@Valid @RequestBody PersonTurnDTO actor){return new Result<Map<String,Object>>().ok(behaviors.prepare(actor));}
    @PostMapping("/internal/behavior/acknowledgements")
    public Result<Map<String,Object>> acknowledgements(@Valid @RequestBody PersonTurnDTO actor){return new Result<Map<String,Object>>().ok(behaviors.acknowledgements(actor));}
    @Data public static class AnalysisResult {
        @Valid @NotNull private PersonTurnDTO actor;
        @NotBlank @Size(max=64) private String job;
        @NotNull @Size(max=65536) private String content;
    }
    @PostMapping("/internal/behavior/complete")
    public Result<Map<String,Object>> complete(@Valid @RequestBody AnalysisResult result){return new Result<Map<String,Object>>().ok(behaviors.complete(result.getActor(),result.getJob(),result.getContent()));}
    @PostMapping("/internal/search")
    public Result<Map<String,Object>> search(@Valid @RequestBody SearchRequest request) {
        return new Result<Map<String,Object>>().ok(service.search(request.getActor(),request.getQuery()));
    }
    @PostMapping("/internal/recent")
    public Result<Map<String,Object>> recent(@Valid @RequestBody SearchRequest request) {
        return new Result<Map<String,Object>>().ok(recent.search(request.getActor(),request.getQuery()));
    }
    @PostMapping("/internal/continuation")
    public Result<Map<String,Object>> continuation(@Valid @RequestBody PersonTurnDTO actor) {
        return new Result<Map<String,Object>>().ok(recent.continuation(actor));
    }
    @PostMapping("/internal/background")
    public Result<Map<String,Object>> background(@Valid @RequestBody PersonTurnDTO actor) {
        return new Result<Map<String,Object>>().ok(service.background(actor));
    }
    @PostMapping("/internal/override")
    public Result<Void> override(@Valid @RequestBody OverrideRequest request) {
        service.override(request.getActor(),request.getAction(),request.getMatch(),request.getReplacement());return new Result<>();
    }
    @GetMapping("/admin/{account}/{person}/facts")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Map<String,Object>> facts(@PathVariable Long account,@PathVariable String person,
            @RequestParam(defaultValue="0") long generation,@RequestParam(defaultValue="1") int page) {
        return new Result<Map<String,Object>>().ok(service.adminRead(account,person,generation,page));
    }
    @GetMapping("/admin/{account}/{person}/portrait")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Map<String,Object>> portrait(@PathVariable Long account,@PathVariable String person,
            @RequestParam(defaultValue="0") long generation) {
        return new Result<Map<String,Object>>().ok(service.adminPortrait(account,person,generation));
    }
}
