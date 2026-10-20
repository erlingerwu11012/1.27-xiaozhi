package xiaozhi.modules.pay.service;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.apache.ibatis.annotations.Update;
import xiaozhi.modules.pay.dao.OneApiProvisioningDao;

@EnabledIfEnvironmentVariable(named="HW_BILLING_TEST_DATABASE",matches="hardware_billing_test_[a-zA-Z0-9_]+")
class HardwareModelPermissionDatabaseTest {
 @Test void realPermissionSqlIsOwnedReplaySafeAndLeavesAimiAlone() throws Exception {
  String db=System.getenv("HW_BILLING_TEST_DATABASE");assertTrue(db.startsWith("hardware_billing_test_"));
  var jdbc=new JdbcTemplate(new DriverManagerDataSource("jdbc:mysql://127.0.0.1:3306/"+db+"?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai","root",System.getenv("HW_BILLING_TEST_PASSWORD")));
  String table=db+".hardware_model_grant_fixture";
  jdbc.execute("CREATE TABLE IF NOT EXISTS "+table+" (id BIGINT PRIMARY KEY,user_id BIGINT,name VARCHAR(64),models TEXT)");
  jdbc.update("DELETE FROM "+table);
  jdbc.update("INSERT INTO "+table+" VALUES(1,1,'xiaozhi-device','old-model'),(2,2,'xiaozhi-device','old-model'),(3,1,'aimi-device','aimi-chat'),(4,1,'xiaozhi-device','')");
  String sql=OneApiProvisioningDao.class.getMethod("enableHardwareModelForOwnedDeviceToken",Long.class,Long.class,String.class).getAnnotation(Update.class).value()[0];
  sql=sql.replace("one_api.tokens",table).replace("#{model}","?").replace("#{id}","?").replace("#{owner}","?");
  assertEquals(1,jdbc.update(sql,"qwen-plus",1L,1L,"qwen-plus"));
  assertEquals(0,jdbc.update(sql,"qwen-plus",1L,1L,"qwen-plus"));
  assertEquals(0,jdbc.update(sql,"qwen-plus",2L,1L,"qwen-plus"));
  assertEquals(0,jdbc.update(sql,"qwen-plus",3L,1L,"qwen-plus"));
  assertEquals(0,jdbc.update(sql,"qwen-plus",4L,1L,"qwen-plus"));
  assertEquals("old-model,qwen-plus",jdbc.queryForObject("SELECT models FROM "+table+" WHERE id=1",String.class));
  assertEquals("aimi-chat",jdbc.queryForObject("SELECT models FROM "+table+" WHERE id=3",String.class));
 }
}
