package xiaozhi.modules.pay.controller;

import java.util.HashMap;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.modules.pay.service.AlipayNotifyService;

/**
 * 支付宝异步通知接口。
 *
 * 支付宝以 application/x-www-form-urlencoded POST；成功回写纯文本 success，失败回写 failure。
 * 该路径在 ShiroConfig 中已配置 anon，验签由 AlipayNotifyService 内部完成。
 */
@Tag(name = "支付宝回调", description = "支付宝电脑网站支付异步通知")
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/pay/alipay")
public class AlipayNotifyController {

    private final AlipayNotifyService alipayNotifyService;

    @PostMapping(value = "/notify", produces = MediaType.TEXT_PLAIN_VALUE)
    @Operation(summary = "支付宝异步通知回调")
    public String notify(@RequestParam Map<String, String> params) {
        boolean ok = alipayNotifyService.handleNotify(params == null ? new HashMap<>() : params);
        return ok ? "success" : "failure";
    }
}
