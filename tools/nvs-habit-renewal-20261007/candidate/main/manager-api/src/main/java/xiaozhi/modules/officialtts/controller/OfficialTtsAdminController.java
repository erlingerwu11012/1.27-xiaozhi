package xiaozhi.modules.officialtts.controller;

import java.util.Map;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.officialtts.entity.OfficialTtsPriceEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsVoiceEntity;
import xiaozhi.modules.officialtts.service.OfficialTtsService;

@RestController
@RequestMapping("/admin/official-tts")
@RequiredArgsConstructor
@Tag(name = "官方TTS管理")
public class OfficialTtsAdminController {
    private final OfficialTtsService officialTtsService;

    @GetMapping("/overview")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Map<String, Object>> overview() {
        return new Result<Map<String, Object>>().ok(officialTtsService.adminOverview());
    }

    @PutMapping("/prices")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<OfficialTtsPriceEntity> price(@RequestBody OfficialTtsPriceEntity price) {
        return new Result<OfficialTtsPriceEntity>().ok(officialTtsService.updatePrice(price));
    }

    @PostMapping("/prices/draft-from")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<OfficialTtsPriceEntity> draftFrom(@RequestBody Map<String, Object> body) {
        Long id = body.get("id") == null ? null : Long.valueOf(String.valueOf(body.get("id")));
        return new Result<OfficialTtsPriceEntity>().ok(officialTtsService.draftFromPublished(id));
    }

    @PostMapping("/prices/publish")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<OfficialTtsPriceEntity> publish(@RequestBody Map<String, Object> body) {
        Long id = body.get("id") == null ? null : Long.valueOf(String.valueOf(body.get("id")));
        String reason = body.get("reason") == null ? "" : String.valueOf(body.get("reason"));
        return new Result<OfficialTtsPriceEntity>().ok(officialTtsService.publishPrice(id, reason));
    }

    @PostMapping("/prices/sync")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<OfficialTtsPriceEntity> sync(@RequestBody Map<String, Object> body) {
        Long id = body.get("id") == null ? null : Long.valueOf(String.valueOf(body.get("id")));
        return new Result<OfficialTtsPriceEntity>().ok(officialTtsService.syncPublished(id));
    }

    @GetMapping("/jobs/{id}/ledger")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Map<String, Object>> ledger(@PathVariable("id") Long id) {
        return new Result<Map<String, Object>>().ok(officialTtsService.jobLedger(id));
    }

    @PostMapping("/notes")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Void> note(@RequestBody Map<String, Object> body) {
        Long jobId = body.get("jobId") == null ? null : Long.valueOf(String.valueOf(body.get("jobId")));
        String operationId = body.get("operationId") == null ? "" : String.valueOf(body.get("operationId"));
        String reason = body.get("reason") == null ? "" : String.valueOf(body.get("reason"));
        String evidence = body.get("evidence") == null ? "" : String.valueOf(body.get("evidence"));
        officialTtsService.addAdminNote(jobId, operationId, reason, evidence);
        return new Result<>();
    }

    @PostMapping("/settle")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Map<String, Object>> settle(@RequestBody Map<String, Object> body) {
        Long jobId = body.get("jobId") == null ? null : Long.valueOf(String.valueOf(body.get("jobId")));
        boolean present = body.containsKey("finalTotal") && body.get("finalTotal") != null
                && !String.valueOf(body.get("finalTotal")).isBlank();
        Long finalTotal = present ? Long.valueOf(String.valueOf(body.get("finalTotal"))) : null;
        boolean confirmZero = Boolean.parseBoolean(String.valueOf(body.getOrDefault("confirmZero", "false")));
        boolean confirmed = Boolean.parseBoolean(String.valueOf(body.getOrDefault("confirmed", "false")));
        String operationId = body.get("operationId") == null ? "" : String.valueOf(body.get("operationId"));
        String reason = body.get("reason") == null ? "" : String.valueOf(body.get("reason"));
        String evidence = body.get("evidence") == null ? "" : String.valueOf(body.get("evidence"));
        return new Result<Map<String, Object>>().ok(officialTtsService.adminSettle(jobId, finalTotal, present,
                confirmZero, confirmed, operationId, reason, evidence));
    }

    @PostMapping("/reconcile")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Void> reconcile(@RequestBody Map<String, Object> body) {
        throw new RenException("use_admin_note_or_settle");
    }

    @PostMapping("/sync-device-token-models")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Integer> syncDeviceTokenModels() {
        return new Result<Integer>().ok(officialTtsService.syncDeviceTokenModels());
    }
}
