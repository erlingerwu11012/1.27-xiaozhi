package xiaozhi.modules.pay.service;

import java.math.BigInteger;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;

/** Only verified paid order snapshots may become cash-valued lots. */
@Service
public class HardwareWalletRechargeService {
    private final JdbcTemplate jdbc;
    private final boolean enabled;
    private final String schema;
    @Value("${hardware.billing.group:}")
    private String hardwareGroup="";
    public HardwareWalletRechargeService(JdbcTemplate jdbc,
            @Value("${hardware.billing.enabled:false}") boolean enabled,
            @Value("${hardware.billing.schema:one_api}") String schema) {
        if(schema==null||!schema.matches("[a-zA-Z][a-zA-Z0-9_]{0,63}"))throw new IllegalArgumentException("invalid billing schema");
        this.jdbc=jdbc;this.enabled=enabled;this.schema=schema;
    }
    public boolean ownsWallet(Long account,Long gatewayUser) {
        if(!enabled||account==null||gatewayUser==null)return false;
        Long count=jdbc.queryForObject("SELECT COUNT(*) FROM "+schema+".hardware_billing_wallet WHERE user_id=? AND product_account=? AND state='enabled'",Long.class,gatewayUser,account.toString());
        return count!=null&&count==1;
    }
    public boolean hasWallet(Long account) {
        if(!enabled||account==null)return false;
        Long count=jdbc.queryForObject("SELECT COUNT(*) FROM "+schema+".hardware_billing_wallet WHERE product_account=?",Long.class,account.toString());
        return count!=null&&count==1;
    }
    /** Provision only a binding resolved by the product service; never a client-supplied user. */
    @Transactional(rollbackFor=Exception.class)
    public void ensureWallet(Long account,SysUserOneapiBindingEntity binding) {
        if(!enabled)return;
        if(account==null||binding==null||binding.getOneapiUserId()==null)throw new IllegalStateException("binding missing");
        Long user=binding.getOneapiUserId();
        List<Map<String,Object>> ready=jdbc.queryForList("SELECT product_account,state FROM "+schema+".hardware_billing_wallet WHERE user_id=?",user);
        if(!ready.isEmpty()) {
            if(!account.toString().equals(String.valueOf(ready.get(0).get("product_account")))||!"enabled".equals(ready.get(0).get("state")))throw new IllegalStateException("wallet binding conflict");
            return;
        }
        Map<String,Object> snapshot=jdbc.queryForMap("SELECT quota,used_quota FROM "+schema+".users WHERE id=? FOR UPDATE",user);
        List<Map<String,Object>> existing=jdbc.queryForList("SELECT product_account,state FROM "+schema+".hardware_billing_wallet WHERE user_id=? FOR UPDATE",user);
        if(!existing.isEmpty()) {
            if(!account.toString().equals(String.valueOf(existing.get(0).get("product_account")))||!"enabled".equals(existing.get(0).get("state")))throw new IllegalStateException("wallet binding conflict");
            return;
        }
        long quota=((Number)snapshot.get("quota")).longValue(),used=((Number)snapshot.get("used_quota")).longValue();
        if(quota<0||used<0)throw new IllegalStateException("invalid quota snapshot");
        BigInteger n=BigInteger.valueOf(quota),d=BigInteger.valueOf(500),gcd=n.gcd(d);
        String points=n.divide(gcd)+"/"+d.divide(gcd);
        long now=System.currentTimeMillis();
        jdbc.update("INSERT INTO "+schema+".hardware_billing_wallet(user_id,product_account,state,created_at,legacy_used_quota) VALUES(?,?,'enabled',?,?)",user,account.toString(),now/1000,used);
        jdbc.update("INSERT INTO "+schema+".hardware_billing_lot(id,user_id,kind,remaining,cny_per_point,paid_cents,granted_points,original_points,created_at) VALUES(?,?,'legacy',?,'0',0,0,?,?)","legacy:"+account,user,points,points,Math.multiplyExact(now,1000000L));
        if(!hardwareGroup.isBlank()) {
            if(!hardwareGroup.matches("[a-zA-Z][a-zA-Z0-9_]{0,31}"))throw new IllegalStateException("invalid hardware group");
            jdbc.update("UPDATE "+schema+".users SET `group`=? WHERE id=?",hardwareGroup,user);
        }
    }

    static String rate(long cents,long points) {
        if(cents<=0||points<=0)throw new IllegalArgumentException("invalid paid recharge snapshot");
        BigInteger n=BigInteger.valueOf(cents),d=BigInteger.valueOf(points).multiply(BigInteger.valueOf(100));
        BigInteger gcd=n.gcd(d);n=n.divide(gcd);d=d.divide(gcd);
        return d.equals(BigInteger.ONE)?n.toString():n+"/"+d;
    }
    @Transactional(rollbackFor=Exception.class)
    public void apply(PayOrderEntity order,SysUserOneapiBindingEntity binding) {
        Long user=binding.getOneapiUserId();
        if(!ownsWallet(order.getUserId(),user))throw new IllegalStateException("hardware wallet ownership mismatch");
        // Same account lock as Go consumption. Payment and consumption cannot lose updates.
        jdbc.queryForObject("SELECT user_id FROM "+schema+".hardware_billing_wallet WHERE user_id=? FOR UPDATE",Long.class,user);
        List<Map<String,Object>> verified=jdbc.queryForList("SELECT amount_cents,quota_points,status FROM pay_order WHERE out_trade_no=? AND user_id=? FOR UPDATE",order.getOutTradeNo(),order.getUserId());
        if(verified.size()!=1)throw new IllegalStateException("paid order missing");
        Map<String,Object> actual=verified.get(0);
        if(!java.util.Set.of("paid","delivered").contains(String.valueOf(actual.get("status"))))throw new IllegalStateException("order not paid");
        long cents=((Number)actual.get("amount_cents")).longValue(),points=((Number)actual.get("quota_points")).longValue();
        if(cents!=order.getAmountCents()||points!=order.getQuotaPoints())throw new IllegalStateException("paid order snapshot mismatch");
        String id="payment:"+order.getOutTradeNo();if(id.length()>128)throw new IllegalStateException("order id too long");
        List<Map<String,Object>> prior=jdbc.queryForList("SELECT user_id,paid_cents,granted_points,kind,cny_per_point FROM "+schema+".hardware_billing_lot WHERE id=? FOR UPDATE",id);
        String ratio=rate(cents,points);
        if(!prior.isEmpty()) {
            Map<String,Object> old=prior.get(0);
            if(((Number)old.get("user_id")).longValue()!=user||((Number)old.get("paid_cents")).longValue()!=cents||((Number)old.get("granted_points")).longValue()!=points||!"paid".equals(old.get("kind"))||!ratio.equals(old.get("cny_per_point")))throw new IllegalStateException("recharge idempotency conflict");
        } else {
            jdbc.update("INSERT INTO "+schema+".hardware_billing_lot(id,user_id,kind,remaining,cny_per_point,paid_cents,granted_points,original_points,created_at) VALUES(?,?,'paid',?,?,?,?,?,?)",id,user,Long.toString(points),ratio,cents,points,Long.toString(points),Math.multiplyExact(System.currentTimeMillis(),1000000L));
        }
        // Eligibility mirror only. Billing and UI use the exact lot ledger.
        BigDecimal remaining=BigDecimal.ZERO;
        for(String value:jdbc.queryForList("SELECT remaining FROM "+schema+".hardware_billing_lot WHERE user_id=? FOR UPDATE",String.class,user))remaining=remaining.add(HardwareBillingReadService.decimal(value));
        long quota=remaining.multiply(BigDecimal.valueOf(500)).setScale(0,RoundingMode.CEILING).longValueExact();
        jdbc.update("UPDATE "+schema+".users SET quota=? WHERE id=?",quota,user);
        if(binding.getOneapiTokenId()!=null)jdbc.update("UPDATE "+schema+".tokens SET remain_quota=? WHERE id=? AND user_id=? AND unlimited_quota=0",quota,binding.getOneapiTokenId(),user);
    }
}
