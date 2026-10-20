package xiaozhi.modules.pay.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.math.BigDecimal;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import com.fasterxml.jackson.databind.ObjectMapper;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;

/** Actual SQL customer projection against the independently seeded Go ledger. */
@EnabledIfEnvironmentVariable(named="HW_BILLING_TEST_DATABASE",matches="hardware_billing_test_[a-zA-Z0-9_]+")
class HardwareBillingReadDatabaseTest {
    JdbcTemplate jdbc; SysUserOneapiBindingDao bindings; HardwareBillingReadService service;
    @BeforeEach void setup() {
        String db=System.getenv("HW_BILLING_TEST_DATABASE");
        assertTrue(db.startsWith("hardware_billing_test_"));
        jdbc=new JdbcTemplate(new DriverManagerDataSource("jdbc:mysql://127.0.0.1:3306/"+db+"?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai","root",System.getenv("HW_BILLING_TEST_PASSWORD")));
        bindings=mock(SysUserOneapiBindingDao.class);
        service=new HardwareBillingReadService(jdbc,new ObjectMapper(),bindings,true,db);
    }
    @Test void actualLedgerShowsMicroFeesAndDoesNotExposeCost() {
        var binding=new SysUserOneapiBindingEntity();binding.setOneapiUserId(70001L);
        when(bindings.selectOne(any())).thenReturn(binding);
        var result=service.calls(70001L,-1,999);
        // A product account mismatch must not reveal even the matching gateway user's bills.
        assertEquals(false,result.get("available"));
        result=service.calls(99070001L,-1,999);
        assertEquals(true,result.get("available"));assertEquals(20L,result.get("total"));
        @SuppressWarnings("unchecked") var bills=(List<Map<String,Object>>)result.get("list");
        assertEquals(20,bills.size());
        BigDecimal points=BigDecimal.ZERO,paid=BigDecimal.ZERO;
        for(var bill:bills) {
            assertEquals("settled",bill.get("state"));assertEquals("fact_add",bill.get("operation"));
            assertFalse(bill.containsKey("costCny"));assertFalse(bill.containsKey("margin"));
            assertFalse(bill.containsKey("price_json"));assertFalse(bill.containsKey("usage_json"));
            points=points.add((BigDecimal)bill.get("points"));paid=paid.add((BigDecimal)bill.get("paidAmountCny"));
        }
        assertEquals(0,points.compareTo(new BigDecimal("120")));
        assertEquals(0,paid.compareTo(new BigDecimal("1.2")));
    }
    @Test void schemaCannotContainSql() {
        assertThrows(IllegalArgumentException.class,()->new HardwareBillingReadService(jdbc,new ObjectMapper(),bindings,true,"one_api;DELETE"));
    }
}
