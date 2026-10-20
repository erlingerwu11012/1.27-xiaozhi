package xiaozhi.modules.pay.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.client.OneApiClient;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.OneapiRechargeLogDao;
import xiaozhi.modules.pay.dao.PayOrderDao;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;
import xiaozhi.modules.pay.service.OneApiProvisioningService;
import xiaozhi.modules.pay.service.UserQuotaService;
import xiaozhi.modules.pay.vo.PayOrderVO;

@ExtendWith(MockitoExtension.class)
class PaymentDeliveryServiceImplTest {

    private static final Long USER_ID = 100L;
    private static final Long ONEAPI_USER_ID = 2L;
    private static final String ORDER_NO = "RE123";
    private static final String TRADE_NO = "MOCK_RE123";

    @Mock
    private PayOrderDao payOrderDao;
    @Mock
    private UserQuotaService userQuotaService;
    @Mock
    private OneApiClient oneApiClient;
    @Mock
    private SysUserOneapiBindingDao bindingDao;
    @Mock
    private OneapiRechargeLogDao rechargeLogDao;
    @Mock
    private OneApiProvisioningService oneApiProvisioningService;

    private PaymentDeliveryServiceImpl deliveryService;

    @BeforeEach
    void setUp() {
        deliveryService = new PaymentDeliveryServiceImpl(
                payOrderDao, userQuotaService, oneApiClient, bindingDao, rechargeLogDao,
                oneApiProvisioningService);
    }

    private PayOrderEntity newOrder(String status) {
        PayOrderEntity o = new PayOrderEntity();
        o.setId(1L);
        o.setOutTradeNo(ORDER_NO);
        o.setUserId(USER_ID);
        o.setQuotaPoints(1000L);
        o.setChannel("mock");
        o.setStatus(status);
        return o;
    }

    private SysUserOneapiBindingEntity newBinding() {
        SysUserOneapiBindingEntity b = new SysUserOneapiBindingEntity();
        b.setId(1L);
        b.setSysUserId(USER_ID);
        b.setOneapiUserId(ONEAPI_USER_ID);
        b.setOneapiUsername("zcs478455026");
        return b;
    }

    @Test
    void orderNotFoundThrows() {
        when(payOrderDao.selectOne(any())).thenReturn(null);
        assertThrows(RenException.class, () -> deliveryService.deliver(ORDER_NO, TRADE_NO));
    }

    @Test
    void deliveredOrderIsIdempotent() {
        when(payOrderDao.selectOne(any())).thenReturn(newOrder(PayConstants.STATUS_DELIVERED));

        PayOrderVO vo = deliveryService.deliver(ORDER_NO, TRADE_NO);

        assertEquals(PayConstants.STATUS_DELIVERED, vo.getStatus());
        verify(oneApiClient, never()).topup(anyLong(), anyLong(), anyString());
        verify(userQuotaService, never()).grantQuota(anyLong(), anyString(), anyLong());
    }

    @Test
    void paidOrderWithoutSuccessLogDoesNotRetryTopup() {
        when(payOrderDao.selectOne(any())).thenReturn(newOrder(PayConstants.STATUS_PAID));
        when(rechargeLogDao.selectCount(any())).thenReturn(0L);

        PayOrderVO vo = deliveryService.deliver(ORDER_NO, TRADE_NO);

        assertEquals(PayConstants.STATUS_PAID, vo.getStatus());
        verify(oneApiClient, never()).topup(anyLong(), anyLong(), anyString());
    }

    @Test
    void existingSuccessLogCompensatesToDeliveredWithoutTopup() {
        PayOrderEntity paid = newOrder(PayConstants.STATUS_PAID);
        when(payOrderDao.selectOne(any())).thenReturn(paid);
        when(rechargeLogDao.selectCount(any())).thenReturn(1L);
        when(payOrderDao.selectById(1L)).thenReturn(newOrder(PayConstants.STATUS_DELIVERED));

        PayOrderVO vo = deliveryService.deliver(ORDER_NO, TRADE_NO);

        assertEquals(PayConstants.STATUS_DELIVERED, vo.getStatus());
        verify(oneApiClient, never()).topup(anyLong(), anyLong(), anyString());
    }

    @Test
    void bindingNotFoundThrowsAndDoesNotDeliver() {
        when(payOrderDao.selectOne(any())).thenReturn(newOrder(PayConstants.STATUS_PENDING));
        when(payOrderDao.update(any(), any())).thenReturn(1);
        when(bindingDao.selectOne(any())).thenReturn(null);

        RenException ex = assertThrows(RenException.class,
                () -> deliveryService.deliver(ORDER_NO, TRADE_NO));

        assertEquals(PayConstants.MSG_ONEAPI_BINDING_NOT_FOUND, ex.getMsg());
        verify(oneApiClient, never()).topup(anyLong(), anyLong(), anyString());
        verify(rechargeLogDao, never()).insert(any());
    }

    @Test
    void topupSuccessDeliversOrder() {
        when(payOrderDao.selectOne(any())).thenReturn(newOrder(PayConstants.STATUS_PENDING));
        when(payOrderDao.update(any(), any())).thenReturn(1);
        when(rechargeLogDao.selectCount(any())).thenReturn(0L);
        when(bindingDao.selectOne(any())).thenReturn(newBinding());
        when(payOrderDao.selectById(1L)).thenReturn(newOrder(PayConstants.STATUS_DELIVERED));

        PayOrderVO vo = deliveryService.deliver(ORDER_NO, TRADE_NO);

        assertEquals(PayConstants.STATUS_DELIVERED, vo.getStatus());
        verify(oneApiClient).topup(ONEAPI_USER_ID, 500000L,
                PayConstants.ONEAPI_RECHARGE_REMARK_PREFIX + ORDER_NO);
        verify(rechargeLogDao).insert(any());
        verify(userQuotaService).grantQuota(USER_ID, ORDER_NO, 1000L);
    }

    @Test
    void topupFailureKeepsPaidAndDoesNotDeliver() {
        when(payOrderDao.selectOne(any())).thenReturn(newOrder(PayConstants.STATUS_PENDING));
        when(payOrderDao.update(any(), any())).thenReturn(1);
        when(rechargeLogDao.selectCount(any())).thenReturn(0L);
        when(bindingDao.selectOne(any())).thenReturn(newBinding());
        doThrowFailure();

        assertThrows(RenException.class, () -> deliveryService.deliver(ORDER_NO, TRADE_NO));

        verify(oneApiClient).topup(anyLong(), anyLong(), anyString());
        verify(rechargeLogDao, never()).insert(any());
        verify(userQuotaService, never()).grantQuota(anyLong(), anyString(), anyLong());
        verify(payOrderDao, times(2)).update(any(), any());
    }

    @Test
    void hardwarePaidRetryUsesLotLedgerAndNeverOldTopup() {
        var hardware=org.mockito.Mockito.mock(xiaozhi.modules.pay.service.HardwareWalletRechargeService.class);
        org.springframework.test.util.ReflectionTestUtils.setField(deliveryService,"hardwareRecharge",hardware);
        PayOrderEntity paid=newOrder(PayConstants.STATUS_PAID);
        SysUserOneapiBindingEntity binding=newBinding();
        when(payOrderDao.selectOne(any())).thenReturn(paid);
        when(rechargeLogDao.selectCount(any())).thenReturn(0L);
        when(hardware.hasWallet(USER_ID)).thenReturn(true);
        when(bindingDao.selectOne(any())).thenReturn(binding);
        when(payOrderDao.selectById(1L)).thenReturn(newOrder(PayConstants.STATUS_DELIVERED));
        assertEquals(PayConstants.STATUS_DELIVERED,deliveryService.deliver(ORDER_NO,TRADE_NO).getStatus());
        verify(hardware).ensureWallet(USER_ID,binding);
        verify(hardware).apply(paid,binding);
        verify(oneApiClient,never()).topup(anyLong(),anyLong(),anyString());
        verify(rechargeLogDao).insert(any());
    }

    private void doThrowFailure() {
        try {
            org.mockito.Mockito.doThrow(new RenException("one-api 充值失败: 测试失败"))
                    .when(oneApiClient).topup(anyLong(), anyLong(), anyString());
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
