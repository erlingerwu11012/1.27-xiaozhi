package xiaozhi.modules.personmemory;

import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.security.user.SecurityUser;

@RestController
@RequiredArgsConstructor
@RequestMapping("/pay/memory-bills")
public class MemoryBillingController {
    private final MemoryBillingService bills;
    @GetMapping
    public Result<Map<String,Object>> read(@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="10") int limit) {
        return new Result<Map<String,Object>>().ok(bills.read(SecurityUser.getUser().getId(),page,limit));
    }
}
