package xiaozhi.modules.pay.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;

/** Read-only customer projection. Never exposes prompts, API costs, keys or margin. */
@Service
public class HardwareBillingReadService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final SysUserOneapiBindingDao bindings;
    private final boolean enabled;
    private final String schema;
    public HardwareBillingReadService(JdbcTemplate jdbc, ObjectMapper json,
            SysUserOneapiBindingDao bindings, @Value("${hardware.billing.enabled:false}") boolean enabled,
            @Value("${hardware.billing.schema:one_api}") String schema) {
        if(schema==null || !schema.matches("[a-zA-Z][a-zA-Z0-9_]{0,63}"))
            throw new IllegalArgumentException("invalid billing schema");
        this.jdbc=jdbc; this.json=json; this.bindings=bindings; this.enabled=enabled;
        this.schema=schema;
    }

    // Fractions are reduced exact values in storage; decimals here are DISPLAY only.
    static BigDecimal decimal(String value) {
        if(value==null||value.isEmpty()) return BigDecimal.ZERO;
        String[] parts=value.split("/",-1);
        if(parts.length==1) return new BigDecimal(value);
        if(parts.length!=2) throw new IllegalArgumentException("invalid ledger amount");
        return new BigDecimal(parts[0]).divide(new BigDecimal(parts[1]),18,RoundingMode.HALF_UP);
    }
    private Long ownedGatewayUser(Long account) {
        SysUserOneapiBindingEntity b=bindings.selectOne(new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id",account));
        return b==null?null:b.getOneapiUserId();
    }
    private Map<String,Object> ownedWallet(Long account) {
        if(!enabled)return null;
        Long owner=ownedGatewayUser(account);if(owner==null)return null;
        List<Map<String,Object>> rows=jdbc.queryForList("SELECT user_id,state,created_at,legacy_used_quota FROM "+schema+".hardware_billing_wallet WHERE user_id=? AND product_account=?",owner,account.toString());
        if(rows.isEmpty())return null;
        if(!"enabled".equals(rows.get(0).get("state")))throw new IllegalStateException("计费钱包暂不可用");
        return rows.get(0);
    }
    private BigDecimal allocationPoints(String text) {
        try {
            BigDecimal result=BigDecimal.ZERO;
            for(JsonNode a:json.readTree(text))result=result.add(decimal(a.path("points").asText()));
            return result;
        } catch(Exception e){throw new IllegalStateException("账单记录格式异常，请联系管理员核对");}
    }
    @org.springframework.transaction.annotation.Transactional(readOnly=true)
    public Map<String,BigDecimal> walletBalance(Long account) {
        Map<String,Object> wallet=ownedWallet(account);if(wallet==null)return null;
        Object owner=wallet.get("user_id");
        BigDecimal legacy=BigDecimal.ZERO,paid=BigDecimal.ZERO;
        for(Map<String,Object> lot:jdbc.queryForList("SELECT kind,remaining FROM "+schema+".hardware_billing_lot WHERE user_id=?",owner)) {
            BigDecimal n=decimal((String)lot.get("remaining"));
            if("legacy".equals(lot.get("kind")))legacy=legacy.add(n);else paid=paid.add(n);
        }
        BigDecimal consumed=BigDecimal.valueOf(((Number)wallet.get("legacy_used_quota")).longValue()).divide(BigDecimal.valueOf(500));
        for(String allocations:jdbc.queryForList("SELECT allocations FROM "+schema+".hardware_billing_bill WHERE user_id=? AND state='settled'",String.class,owner))consumed=consumed.add(allocationPoints(allocations));
        return Map.of("balance",legacy.add(paid),"legacyPoints",legacy,"paidPoints",paid,"totalConsume",consumed);
    }
    @org.springframework.transaction.annotation.Transactional(readOnly=true)
    public Map<java.time.LocalDate,BigDecimal> dailyUsage(Long account,long start,long end) {
        Map<String,Object> wallet=ownedWallet(account);if(wallet==null)return null;
        Object owner=wallet.get("user_id");long cutoff=((Number)wallet.get("created_at")).longValue();
        Map<java.time.LocalDate,BigDecimal> days=new java.util.HashMap<>();
        // Old logs remain immutable. Only the portion before cutover is included.
        for(Map<String,Object> row:jdbc.queryForList("SELECT FLOOR((created_at+28800)/86400) day_index,SUM(quota) quota FROM "+schema+".logs WHERE user_id=? AND type=2 AND created_at>=? AND created_at<? GROUP BY day_index",owner,start,Math.min(end,cutoff))) {
            java.time.LocalDate day=java.time.LocalDate.ofEpochDay(((Number)row.get("day_index")).longValue());
            days.merge(day,new BigDecimal(row.get("quota").toString()).divide(BigDecimal.valueOf(500)),BigDecimal::add);
        }
        for(Map<String,Object> row:jdbc.queryForList("SELECT settled_at,allocations FROM "+schema+".hardware_billing_bill WHERE user_id=? AND state IN ('settled','refunded') AND settled_at>=? AND settled_at<?",owner,start,end)) {
            java.time.LocalDate day=java.time.Instant.ofEpochSecond(((Number)row.get("settled_at")).longValue()).atZone(java.time.ZoneId.of("Asia/Shanghai")).toLocalDate();
            days.merge(day,allocationPoints((String)row.get("allocations")),BigDecimal::add);
        }
        for(Map<String,Object> row:jdbc.queryForList("SELECT created_at,allocations FROM "+schema+".hardware_billing_adjustment WHERE user_id=? AND kind='refund' AND created_at>=? AND created_at<?",owner,start,end)) {
            java.time.LocalDate day=java.time.Instant.ofEpochSecond(((Number)row.get("created_at")).longValue()).atZone(java.time.ZoneId.of("Asia/Shanghai")).toLocalDate();
            days.merge(day,allocationPoints((String)row.get("allocations")).negate(),BigDecimal::add);
        }
        return days;
    }
    @org.springframework.transaction.annotation.Transactional(readOnly=true)
    public Map<String,Object> calls(Long account, int page, int limit) {
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("available",false); result.put("list",List.of());result.put("total",0);
        if(!enabled) return result;
        Long owner=ownedGatewayUser(account); if(owner==null) return result;
        page=Math.max(1,Math.min(page,10000));limit=Math.max(1,Math.min(limit,100));
        Long n=jdbc.queryForObject("SELECT COUNT(*) FROM "+schema+".hardware_billing_wallet WHERE user_id=? AND product_account=? AND state='enabled'",Long.class,owner,account.toString());
        if(n==null||n!=1) return result;
        List<Map<String,Object>> rows=jdbc.queryForList("SELECT id,state,price_json,usage_json,allocations,created_at,settled_at FROM "+schema+".hardware_billing_bill WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",owner,limit,(page-1)*limit);
        List<Map<String,Object>> list=new ArrayList<>();
        for(Map<String,Object> row:rows) {
            try {
                JsonNode price=json.readTree(String.valueOf(row.get("price_json")));
                String usageText=(String)row.get("usage_json");
                JsonNode usage=usageText==null||usageText.isBlank()?json.createObjectNode():json.readTree(usageText);
                JsonNode splits=json.readTree(String.valueOf(row.get("allocations")));
                BigDecimal paid=BigDecimal.ZERO,points=BigDecimal.ZERO,legacy=BigDecimal.ZERO;
                for(JsonNode a:splits) {
                    BigDecimal amount=decimal(a.path("points").asText("0"));points=points.add(amount);
                    if("legacy".equals(a.path("kind").asText())) legacy=legacy.add(amount);
                    else paid=paid.add(decimal(a.path("sale_cny").asText("0")));
                }
                String state=String.valueOf(row.get("state"));boolean settled="settled".equals(state)||"refunded".equals(state);
                Map<String,Object> item=new LinkedHashMap<>();
                item.put("id",row.get("id"));item.put("state",state);item.put("model",price.path("model").asText());
                item.put("operation",price.path("operation").asText());item.put("unit",price.path("unit").asText());
                item.put("inputTokens",usage.path("confirmed").asBoolean()?usage.get("input_tokens"):null);
                item.put("outputTokens",usage.path("confirmed").asBoolean()?usage.get("output_tokens"):null);
                item.put("cachedTokens",usage.get("cached_tokens"));item.put("units",usage.get("units"));
                item.put("createdAt",row.get("created_at"));item.put("settledAt",row.get("settled_at"));
                item.put("points",settled?points:null);item.put("paidAmountCny",settled?paid:null);
                item.put("legacyPoints",settled?legacy:null);item.put("reservedPoints",settled?null:points);
                list.add(item);
            } catch(Exception e) {
                // A malformed financial row is an error, not a fabricated zero bill.
                throw new IllegalStateException("账单记录格式异常，请联系管理员核对");
            }
        }
        result.put("available",true);result.put("list",list);
        result.put("total",jdbc.queryForObject("SELECT COUNT(*) FROM "+schema+".hardware_billing_bill WHERE user_id=?",Long.class,owner));
        return result;
    }
}
