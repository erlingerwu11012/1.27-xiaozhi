package xiaozhi.modules.personmemory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.service.OneApiBindingService;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;

@Component
public class MemoryGatewayClient {
    private final OneApiBindingService binding;
    private final ObjectMapper json;
    private final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofMillis(500)).followRedirects(HttpClient.Redirect.NEVER).build();
    @Value("${memory.gateway.url:http://127.0.0.1:3011}") private String base;
    @Value("${memory.gateway.service-secret:}") private String secret;
    @Value("${memory.fact-strategy:lite}") private String factStrategy;
    @Value("${memory.search-strategy:lite}") private String searchStrategy;
    @Value("${memory.portrait-strategy:lite}") private String portraitStrategy;

    public MemoryGatewayClient(OneApiBindingService binding,ObjectMapper json) {this.binding=binding;this.json=json;}

    public Map<String,Object> request(Long accountId,String personId,long generation,String method,String path,Object body,String idempotency,Duration timeout) {
        try {
            URI origin=URI.create(base);
            if (origin.getUserInfo()!=null || origin.getQuery()!=null || !("https".equals(origin.getScheme()) || "http".equals(origin.getScheme()) && "127.0.0.1".equals(origin.getHost()))) throw new RenException("记忆网关地址无效");
            if (secret.length()<32) throw new RenException("记忆服务认证未配置");
            OneApiDeviceTokenVO token=binding.resolveDeviceToken(accountId);
            String expiry=Long.toString(Instant.now().getEpochSecond()+120);
            String canonical=String.join("\n","memory-v1",Long.toString(token.getOneapiUserId()),Long.toString(accountId),personId,Long.toString(generation),expiry);
            Mac mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
            String signature=HexFormat.of().formatHex(mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8)));
            String authorization=token.getToken().startsWith("sk-")?token.getToken():"sk-"+token.getToken();
            HttpRequest.Builder request=HttpRequest.newBuilder(URI.create(base.replaceAll("/$","")+"/bailian/api/v2/apps/memory/"+path)).timeout(timeout)
                .header("Authorization","Bearer "+authorization).header("Content-Type","application/json")
                .header("X-Memory-Account",accountId.toString()).header("X-Memory-Person",personId)
                .header("X-Memory-Generation",Long.toString(generation)).header("X-Memory-Expires",expiry).header("X-Memory-Signature",signature)
                .header("X-Memory-Strategy",path.contains("search")?searchStrategy:factStrategy)
                .header("X-Memory-Portrait-Strategy",portraitStrategy);
            if(idempotency!=null) request.header("Idempotency-Key",idempotency);
            request.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body)));
            HttpResponse<String> response=client.send(request.build(),HttpResponse.BodyHandlers.ofString());
            if(response.statusCode()<200 || response.statusCode()>=300) throw new GatewayFailure(response.statusCode());
            if(response.body().length()>4*1024*1024) throw new RenException("记忆响应过大");
            return json.readValue(response.body(),new TypeReference<Map<String,Object>>(){});
        } catch(GatewayFailure e) {throw e;}
        catch(InterruptedException e) {Thread.currentThread().interrupt();throw new GatewayFailure(598);}
        catch(Exception e) {throw new GatewayFailure(599);}
    }
    public String cloudUserId(Long accountId,String personId,long generation) {
        OneApiDeviceTokenVO token=binding.resolveDeviceToken(accountId);
        return "re_"+sha(String.join(":",token.getOneapiUserId().toString(),accountId.toString(),personId,Long.toString(generation))).substring(0,60);
    }
    public Map<String,Object> operationStatus(Long account,String person,long generation,String idempotency) {
        OneApiDeviceTokenVO token=binding.resolveDeviceToken(account);
        String scope=sha(String.join(":",token.getOneapiUserId().toString(),cloudUserId(account,person,generation),"POST","add-async",idempotency));
        return request(account,person,generation,"GET","operations/"+scope,null,null,Duration.ofSeconds(3));
    }
    public static String sha(String value) {
        try {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
        catch(Exception e) {throw new IllegalStateException(e);}
    }
    public static class GatewayFailure extends RuntimeException {
        private final int status;
        public GatewayFailure(int status) {super("memory_gateway_status_"+status);this.status=status;}
        public int status(){return status;}
    }
}
