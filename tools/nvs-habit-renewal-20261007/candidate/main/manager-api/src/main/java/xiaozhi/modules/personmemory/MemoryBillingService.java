package xiaozhi.modules.personmemory;

import java.math.*;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;

/** Read the bound account's immutable fee ledger; never expose memory bodies. */
@Service
@RequiredArgsConstructor
public class MemoryBillingService {
    private final JdbcTemplate jdbc;
    public Map<String,Object> read(Long account,int page,int size) {
        page=Math.clamp(page,1,100000);size=Math.clamp(size,1,50);
        var owners=jdbc.queryForList("SELECT oneapi_user_id FROM sys_user_oneapi_binding WHERE sys_user_id=?",Long.class,account);
        if(owners.size()!=1)return Map.of("available",true,"list",List.of(),"total",0);
        Long owner=owners.get(0);
        String source="SELECT c.created_at,c.operation,c.strategy,c.units,c.exact_quota,b.state,b.charged,b.held FROM one_api.memory_charges c JOIN one_api.bailian_bills b ON b.id=c.bill_id WHERE c.user_id=? UNION ALL SELECT h.sampled_at,'storage','lite',h.fact_count,h.exact_quota,h.state,0,0 FROM one_api.memory_storage_hours h WHERE h.user_id=? AND h.state IN('pending','debt') AND (h.bill_id IS NULL OR h.bill_id='')";
        try {
            Long total=jdbc.queryForObject("SELECT COUNT(*) FROM ("+source+") fees",Long.class,owner,owner);
            var rows=jdbc.queryForList("SELECT * FROM ("+source+") fees ORDER BY created_at DESC LIMIT ? OFFSET ?",owner,owner,size,(page-1)*size);
            var result=new ArrayList<Map<String,Object>>();
            for(var row:rows) {
                var value=new LinkedHashMap<String,Object>();
                value.put("createdAt",((Number)row.get("created_at")).longValue()*1000);
                for(String key:List.of("operation","strategy","units","state"))value.put(key,row.get(key));
                value.put("amountCny",nominalCny(Objects.toString(row.get("exact_quota"),"0")));
                value.put("chargedPoints",new BigDecimal(Objects.toString(row.get("charged"),"0")).divide(new BigDecimal("500"),3,RoundingMode.HALF_UP));
                result.add(value);
            }
            return Map.of("available",true,"list",result,"total",total==null?0:total);
        }catch(DataAccessException error) {
            return Map.of("available",false,"list",List.of(),"total",0);
        }
    }
    static BigDecimal nominalCny(String exactQuota) {
        String[] parts=exactQuota.split("/",-1);
        BigDecimal value=new BigDecimal(parts[0]);
        if(parts.length==2)value=value.divide(new BigDecimal(parts[1]),18,RoundingMode.HALF_UP);
        else if(parts.length!=1)throw new IllegalArgumentException("invalid_exact_quota");
        return value.multiply(new BigDecimal("7")).divide(new BigDecimal("500000"),10,RoundingMode.HALF_UP);
    }
}
