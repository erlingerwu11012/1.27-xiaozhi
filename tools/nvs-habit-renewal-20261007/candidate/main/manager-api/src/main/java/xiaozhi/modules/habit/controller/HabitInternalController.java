package xiaozhi.modules.habit.controller;
import java.util.Map;
import org.springframework.web.bind.annotation.*;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.habit.service.HabitSyncService;
@RestController @RequiredArgsConstructor @RequestMapping("/habits/internal")
public class HabitInternalController {
    private final HabitSyncService sync;
    @GetMapping("/{id}") public Result<Map<String,Object>> record(@PathVariable Integer id){return new Result<Map<String,Object>>().ok(sync.record(id));}
    @PostMapping("/ack") public Result<Map<String,Object>> ack(@RequestBody HabitSyncService.Ack ack){return new Result<Map<String,Object>>().ok(Map.of("accepted",sync.acknowledge(ack)));}
}
