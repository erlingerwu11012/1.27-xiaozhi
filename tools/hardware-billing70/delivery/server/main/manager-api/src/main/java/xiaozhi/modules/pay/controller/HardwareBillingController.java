package xiaozhi.modules.pay.controller;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.pay.service.HardwareBillingReadService;
import xiaozhi.modules.security.user.SecurityUser;

@RestController
@RequestMapping("/pay/billing")
@RequiredArgsConstructor
public class HardwareBillingController {
    private final HardwareBillingReadService billing;
    @GetMapping("/calls")
    public Result<Map<String,Object>> calls(
            @RequestParam(defaultValue="1") int page,
            @RequestParam(defaultValue="20") int limit) {
        return new Result<Map<String,Object>>().ok(billing.calls(SecurityUser.getUser().getId(),page,limit));
    }
}
