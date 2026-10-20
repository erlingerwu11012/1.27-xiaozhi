package xiaozhi.modules.pay.service;

import xiaozhi.common.service.BaseService;
import xiaozhi.modules.pay.entity.UserQuotaEntity;
import xiaozhi.modules.pay.vo.BillingSummaryVO;
import xiaozhi.modules.pay.vo.UserQuotaVO;

/**
 * 用户额度 Service
 */
public interface UserQuotaService extends BaseService<UserQuotaEntity> {

    /**
     * 查询当前用户额度与最近流水
     */
    UserQuotaVO getMyQuota(Long userId);

    /**
     * 查询当前用户账单汇总（余额 + 每日用量/账单）。
     *
     * @param userId 当前登录用户ID（服务端强制，不信任前端传入）
     * @param days   统计天数（建议 7 / 30）
     */
    BillingSummaryVO getBillingSummary(Long userId, int days);

    /**
     * 发放额度（幂等：同一订单重复调用不会重复加额度）
     *
     * @param userId  用户ID
     * @param orderNo 关联订单号
     * @param points  发放点数
     */
    void grantQuota(Long userId, String orderNo, long points);
}
