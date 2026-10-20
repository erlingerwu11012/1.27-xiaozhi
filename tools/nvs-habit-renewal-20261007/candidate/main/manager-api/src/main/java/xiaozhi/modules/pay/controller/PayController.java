package xiaozhi.modules.pay.controller;

import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.Parameters;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.page.PageData;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.pay.dto.OrderCreateDTO;
import xiaozhi.modules.pay.service.MockPayService;
import xiaozhi.modules.pay.service.PayOrderService;
import xiaozhi.modules.pay.service.PayPackageService;
import xiaozhi.modules.pay.service.UserQuotaService;
import xiaozhi.modules.pay.vo.BillingSummaryVO;
import xiaozhi.modules.pay.vo.PayOrderVO;
import xiaozhi.modules.pay.vo.PayPackageVO;
import xiaozhi.modules.pay.vo.UserQuotaVO;
import xiaozhi.modules.security.user.SecurityUser;

/**
 * 支付接口（阶段1：支付基础设施 + mock 支付闭环）
 */
@Tag(name = "支付", description = "套餐、订单、额度相关接口（阶段1含 mock 测试支付）")
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/pay")
public class PayController {

    private final PayPackageService payPackageService;
    private final PayOrderService payOrderService;
    private final UserQuotaService userQuotaService;
    private final MockPayService mockPayService;

    @GetMapping("/packages")
    @Operation(summary = "查询启用中的套餐列表")
    public Result<List<PayPackageVO>> packages() {
        List<PayPackageVO> list = payPackageService.listEnabled();
        return new Result<List<PayPackageVO>>().ok(list);
    }

    @PostMapping("/order/create")
    @Operation(summary = "创建支付订单（阶段1仅 mock 渠道可创建）")
    public Result<PayOrderVO> createOrder(@Valid @RequestBody OrderCreateDTO dto) {
        Long userId = SecurityUser.getUser().getId();
        PayOrderVO vo = payOrderService.create(userId, dto);
        return new Result<PayOrderVO>().ok(vo);
    }

    @GetMapping("/order/query/{orderNo}")
    @Operation(summary = "查询当前用户自己的订单")
    public Result<PayOrderVO> queryOrder(@PathVariable("orderNo") String orderNo) {
        Long userId = SecurityUser.getUser().getId();
        PayOrderVO vo = payOrderService.queryByOrderNo(userId, orderNo);
        return new Result<PayOrderVO>().ok(vo);
    }

    /**
     * 【测试接口】仅阶段1内部测试使用，接入真实支付前可关闭。
     */
    @PostMapping("/mock/notify/{orderNo}")
    @Operation(summary = "模拟支付成功（测试接口，仅能操作自己的订单）")
    public Result<PayOrderVO> mockNotify(@PathVariable("orderNo") String orderNo) {
        Long userId = SecurityUser.getUser().getId();
        PayOrderVO vo = mockPayService.mockNotify(userId, orderNo);
        return new Result<PayOrderVO>().ok(vo);
    }

    @GetMapping("/quota/me")
    @Operation(summary = "查询当前用户额度与最近流水")
    public Result<UserQuotaVO> myQuota() {
        Long userId = SecurityUser.getUser().getId();
        UserQuotaVO vo = userQuotaService.getMyQuota(userId);
        return new Result<UserQuotaVO>().ok(vo);
    }

    @GetMapping("/billing/summary")
    @Operation(summary = "查询当前用户账单汇总（余额 + 每日用量/账单）")
    public Result<BillingSummaryVO> billingSummary(
            @Parameter(description = "统计天数，支持 7 或 30") @RequestParam(value = "days", required = false, defaultValue = "7") Integer days) {
        Long userId = SecurityUser.getUser().getId();
        BillingSummaryVO vo = userQuotaService.getBillingSummary(userId, days == null ? 7 : days);
        return new Result<BillingSummaryVO>().ok(vo);
    }

    @GetMapping("/orders")
    @Operation(summary = "分页查询当前用户订单")
    @Parameters({
            @Parameter(name = Constant.PAGE, description = "当前页码，从1开始", required = true),
            @Parameter(name = Constant.LIMIT, description = "每页显示记录数", required = true),
    })
    public Result<PageData<PayOrderVO>> orders(
            @Parameter(hidden = true) @RequestParam Map<String, Object> params) {
        Long userId = SecurityUser.getUser().getId();
        PageData<PayOrderVO> page = payOrderService.page(userId, params);
        return new Result<PageData<PayOrderVO>>().ok(page);
    }
}
