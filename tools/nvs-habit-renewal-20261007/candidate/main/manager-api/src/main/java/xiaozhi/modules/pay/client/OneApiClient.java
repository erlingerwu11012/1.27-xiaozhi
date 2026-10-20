package xiaozhi.modules.pay.client;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Component;

import cn.hutool.http.HttpRequest;
import cn.hutool.http.HttpResponse;
import cn.hutool.json.JSONObject;
import cn.hutool.json.JSONUtil;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.config.OneApiProperties;

/**
 * one-api 官方管理 API 客户端。
 *
 * 安全约定：
 * - 不打印 Authorization / token 明文；
 * - topup 不自动重试（失败直接抛异常，由调用方决定状态）；
 * - 只调用官方 /api/topup，不直接改 one_api 数据库。
 */
@Slf4j
@Component
public class OneApiClient {

    private final OneApiProperties properties;

    public OneApiClient(OneApiProperties properties) {
        this.properties = properties;
    }

    /**
     * 给 one-api 用户充值 quota（官方 /api/topup）。
     *
     * @param userId one-api 用户ID
     * @param quota  充值 quota 数量（正数）
     * @param remark 备注，必须包含订单号，用于审计
     */
    public void topup(long userId, long quota, String remark) {
        String token = requireAdminToken();

        JSONObject body = JSONUtil.createObj()
                .set("user_id", userId)
                .set("quota", quota)
                .set("remark", remark);

        String url = baseUrl() + "/api/topup";
        HttpResponse response;
        try {
            response = HttpRequest.post(url)
                    .header("Authorization", "Bearer " + token)
                    .header("Content-Type", "application/json")
                    .body(body.toString())
                    .setConnectionTimeout(properties.getConnectTimeoutMs())
                    .setReadTimeout(properties.getReadTimeoutMs())
                    .execute();
        } catch (Exception e) {
            log.error("one-api topup 调用异常: userId={}, quota={}, err={}",
                    userId, quota, e.getMessage());
            throw new RenException("one-api 充值失败: " + abbreviate(e.getMessage()));
        }

        if (response.getStatus() != 200) {
            log.error("one-api topup HTTP {}: userId={}, quota={}",
                    response.getStatus(), userId, quota);
            throw new RenException("one-api 充值失败(HTTP " + response.getStatus() + ")");
        }

        JSONObject resp = parseBody(response.body());
        if (!Boolean.TRUE.equals(resp.getBool("success"))) {
            String message = resp.getStr("message", "未知错误");
            log.error("one-api topup 返回失败: userId={}, quota={}, msg={}",
                    userId, quota, message);
            throw new RenException("one-api 充值失败: " + abbreviate(message));
        }
        log.info("one-api topup 成功: userId={}, quota={}, remark={}", userId, quota, remark);
    }

    /**
     * 可选：查询 one-api 用户列表（admin token）。
     */
    public JSONObject listUsers() {
        String token = requireAdminToken();
        String url = baseUrl() + "/api/user/?p=0&page_size=100";
        HttpResponse response = HttpRequest.get(url)
                .header("Authorization", "Bearer " + token)
                .setConnectionTimeout(properties.getConnectTimeoutMs())
                .setReadTimeout(properties.getReadTimeoutMs())
                .execute();
        if (response.getStatus() != 200) {
            throw new RenException("one-api 查询用户失败(HTTP " + response.getStatus() + ")");
        }
        return parseBody(response.body());
    }

    /**
     * 可选：查询当前 token 对应用户信息（需传入用户自己的 token）。
     */
    public JSONObject getUserSelf(String userToken) {
        if (StringUtils.isBlank(userToken)) {
            throw new RenException("one-api 用户 token 缺失");
        }
        String url = baseUrl() + "/api/user/self";
        HttpResponse response = HttpRequest.get(url)
                .header("Authorization", "Bearer " + userToken)
                .setConnectionTimeout(properties.getConnectTimeoutMs())
                .setReadTimeout(properties.getReadTimeoutMs())
                .execute();
        if (response.getStatus() != 200) {
            throw new RenException("one-api 查询当前用户失败(HTTP " + response.getStatus() + ")");
        }
        return parseBody(response.body());
    }

    private String requireAdminToken() {
        String token = properties.getAdminToken();
        if (StringUtils.isBlank(token)) {
            throw new RenException("one-api admin token 未配置");
        }
        return token;
    }

    private String baseUrl() {
        return StringUtils.removeEnd(properties.getBaseUrl().trim(), "/");
    }

    private JSONObject parseBody(String body) {
        if (StringUtils.isBlank(body)) {
            return JSONUtil.createObj();
        }
        return JSONUtil.parseObj(body);
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "网络异常";
        }
        return s.length() > 200 ? s.substring(0, 200) : s;
    }
}
