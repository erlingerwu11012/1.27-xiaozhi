package xiaozhi.modules.pay.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import com.fasterxml.jackson.databind.ObjectMapper;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;

@EnabledIfEnvironmentVariable(named="HW_BILLING_TEST_DATABASE",matches="hardware_billing_test_[a-zA-Z0-9_]+")
class HardwareWalletDatabaseTest {
 JdbcTemplate jdbc;TransactionTemplate tx;HardwareWalletRechargeService recharge;
 HardwareBillingReadService read;PayOrderEntity order;SysUserOneapiBindingEntity binding;
 long now=System.currentTimeMillis()/1000;
 @BeforeEach void setup(){
  String db=System.getenv("HW_BILLING_TEST_DATABASE");assertTrue(db.startsWith("hardware_billing_test_"));
  var ds=new DriverManagerDataSource("jdbc:mysql://127.0.0.1:3306/"+db+"?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai","root",System.getenv("HW_BILLING_TEST_PASSWORD"));
  jdbc=new JdbcTemplate(ds);tx=new TransactionTemplate(new DataSourceTransactionManager(ds));
  recharge=new HardwareWalletRechargeService(jdbc,true,db);
  jdbc.execute("CREATE TABLE IF NOT EXISTS pay_order(out_trade_no VARCHAR(100) PRIMARY KEY,user_id BIGINT,amount_cents INT,quota_points BIGINT,status VARCHAR(24))");
  jdbc.execute("CREATE TABLE IF NOT EXISTS users(id BIGINT PRIMARY KEY,quota BIGINT,used_quota BIGINT NOT NULL DEFAULT 0)");
  jdbc.execute("CREATE TABLE IF NOT EXISTS tokens(id BIGINT PRIMARY KEY,user_id BIGINT,remain_quota BIGINT,unlimited_quota INT)");
  jdbc.execute("CREATE TABLE IF NOT EXISTS logs(id BIGINT PRIMARY KEY,user_id BIGINT,type INT,created_at BIGINT,quota BIGINT)");
  jdbc.update("DELETE FROM hardware_billing_adjustment WHERE user_id=70002");jdbc.update("DELETE FROM hardware_billing_bill WHERE user_id=70002");jdbc.update("DELETE FROM hardware_billing_lot WHERE user_id=70002");jdbc.update("DELETE FROM hardware_billing_wallet WHERE user_id=70002");
  jdbc.update("DELETE FROM pay_order WHERE user_id=99070002");jdbc.update("DELETE FROM users WHERE id=70002");jdbc.update("DELETE FROM tokens WHERE id=70002");jdbc.update("DELETE FROM logs WHERE user_id=70002");
  jdbc.update("INSERT INTO hardware_billing_wallet(user_id,product_account,state,created_at,legacy_used_quota) VALUES(70002,'99070002','enabled',?,1000)",now-60);
  jdbc.update("INSERT INTO users(id,quota) VALUES(70002,0)");jdbc.update("INSERT INTO tokens VALUES(70002,70002,0,0)");
  jdbc.update("INSERT INTO pay_order VALUES('isolated-paid-order',99070002,100,100,'paid')");
  order=new PayOrderEntity();order.setUserId(99070002L);order.setOutTradeNo("isolated-paid-order");order.setAmountCents(100);order.setQuotaPoints(100L);
  binding=new SysUserOneapiBindingEntity();binding.setOneapiUserId(70002L);binding.setOneapiTokenId(70002L);
  var bindings=mock(SysUserOneapiBindingDao.class);when(bindings.selectOne(any())).thenReturn(binding);
  read=new HardwareBillingReadService(jdbc,new ObjectMapper(),bindings,true,db);
 }
 void apply(){tx.execute(status->{recharge.apply(order,binding);return null;});}
 @Test void concurrentPaidCallbacksCreditOneCashLot()throws Exception{
  var pool=Executors.newFixedThreadPool(4);
  try{List<Future<?>> jobs=new ArrayList<>();for(int i=0;i<12;i++)jobs.add(pool.submit(this::apply));for(var job:jobs)job.get();}finally{pool.shutdownNow();}
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM hardware_billing_lot WHERE user_id=70002",Integer.class));
  assertEquals("1/100",jdbc.queryForObject("SELECT cny_per_point FROM hardware_billing_lot WHERE user_id=70002",String.class));
  assertEquals(50000L,jdbc.queryForObject("SELECT quota FROM users WHERE id=70002",Long.class));
  assertEquals(0,read.walletBalance(99070002L).get("balance").compareTo(new BigDecimal("100")));
  order.setAmountCents(101);assertThrows(IllegalStateException.class,this::apply);
 }
 @Test void newBindingBootstrapsExactLegacySnapshotOnce()throws Exception{
  jdbc.update("DELETE FROM hardware_billing_wallet WHERE user_id=70002");
  jdbc.update("UPDATE users SET quota=1001,used_quota=500 WHERE id=70002");
  var pool=Executors.newFixedThreadPool(4);
  try{List<Future<?>> jobs=new ArrayList<>();for(int i=0;i<8;i++)jobs.add(pool.submit(()->tx.execute(st->{recharge.ensureWallet(99070002L,binding);return null;})));for(var job:jobs)job.get();}finally{pool.shutdownNow();}
  assertEquals("1001/500",jdbc.queryForObject("SELECT remaining FROM hardware_billing_lot WHERE user_id=70002",String.class));
  assertEquals(500L,jdbc.queryForObject("SELECT legacy_used_quota FROM hardware_billing_wallet WHERE user_id=70002",Long.class));
  assertThrows(IllegalStateException.class,()->tx.execute(st->{recharge.ensureWallet(999L,binding);return null;}));
 }
 @Test void unpaidOrWrongAccountCannotCreatePaidLot(){
  jdbc.update("UPDATE pay_order SET status='pending' WHERE out_trade_no=?",order.getOutTradeNo());
  assertThrows(IllegalStateException.class,this::apply);
  assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM hardware_billing_lot WHERE user_id=70002",Integer.class));
  assertFalse(recharge.ownsWallet(999L,70002L));assertNull(read.walletBalance(999L));
  assertEquals("29/50000",HardwareWalletRechargeService.rate(2900,50000));
  assertEquals("99/200000",HardwareWalletRechargeService.rate(9900,200000));
 }
 @Test void displayedBalanceDailyBillsAndRefundMatchExactLedger(){
  apply();String alloc="[{\"lot_id\":\"payment:isolated-paid-order\",\"kind\":\"paid\",\"points\":\"6\",\"sale_cny\":\"3/50\"}]";
  jdbc.update("UPDATE hardware_billing_lot SET remaining='94' WHERE user_id=70002");
  jdbc.update("INSERT INTO hardware_billing_bill(id,user_id,payload_hash,price_json,usage_json,usage_hash,state,cost_cny,sale_cny,allocations,reservation_json,created_at,settled_at) VALUES('sql-actual-bill',70002,?,'{}','{}',?,'settled','9/500','3/50',?,'[]',?,?)","a".repeat(64),"b".repeat(64),alloc,now,now);
  jdbc.update("INSERT INTO logs VALUES(70002,70002,2,?,1000)",now-62);
  jdbc.update("INSERT INTO logs VALUES(70003,70002,2,?,99999)",now);
  var balance=read.walletBalance(99070002L);assertEquals(0,balance.get("balance").compareTo(new BigDecimal("94")));assertEquals(0,balance.get("totalConsume").compareTo(new BigDecimal("8")));
  BigDecimal daily=read.dailyUsage(99070002L,now-100,now+10).values().stream().reduce(BigDecimal.ZERO,BigDecimal::add);assertEquals(0,daily.compareTo(new BigDecimal("8")));
  jdbc.update("UPDATE hardware_billing_bill SET state='refunded' WHERE id='sql-actual-bill'");jdbc.update("UPDATE hardware_billing_lot SET remaining='100' WHERE user_id=70002");
  jdbc.update("INSERT INTO hardware_billing_adjustment(id,bill_id,user_id,kind,allocations,created_at) VALUES('refund-sql','sql-actual-bill',70002,'refund',?,?)",alloc,now+1);
  daily=read.dailyUsage(99070002L,now-100,now+10).values().stream().reduce(BigDecimal.ZERO,BigDecimal::add);assertEquals(0,daily.compareTo(new BigDecimal("2")));
  assertEquals(0,read.walletBalance(99070002L).get("balance").compareTo(new BigDecimal("100")));
 }
}
