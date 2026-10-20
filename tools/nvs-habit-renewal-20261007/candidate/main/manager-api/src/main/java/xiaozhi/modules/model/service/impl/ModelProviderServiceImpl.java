package xiaozhi.modules.model.service.impl;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.fasterxml.jackson.core.type.TypeReference;

import cn.hutool.json.JSONArray;
import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.page.PageData;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.common.user.UserDetail;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.knowledge.dao.KnowledgeBaseDao;
import xiaozhi.modules.knowledge.entity.KnowledgeBaseEntity;
import xiaozhi.modules.model.config.McpGatewayProperties;
import xiaozhi.modules.model.dao.ModelProviderDao;
import xiaozhi.modules.model.dto.ModelProviderDTO;
import xiaozhi.modules.model.entity.ModelProviderEntity;
import xiaozhi.modules.model.service.ModelProviderService;
import xiaozhi.modules.model.util.JsonSchemaToFieldsConverter;
import xiaozhi.modules.security.user.SecurityUser;

@Service
@AllArgsConstructor
@Slf4j
public class ModelProviderServiceImpl extends BaseServiceImpl<ModelProviderDao, ModelProviderEntity>
        implements ModelProviderService {

    private final ModelProviderDao modelProviderDao;
    private final KnowledgeBaseDao knowledgeBaseDao;
    private final RestTemplate restTemplate;
    private final McpGatewayProperties mcpGatewayProperties;

    @Override
    public List<ModelProviderDTO> getPluginList() {
        // Step 0：在查询数据库之前，自动从 MCP 网关同步工具到 ai_model_provider（UPSERT），失败则降级仅用库内数据
        if (mcpGatewayProperties.isEnabled()) {
            syncMcpToolsToDb();
        }

        // 1. 获取插件列表（含已同步的 MCP 工具）
        LambdaQueryWrapper<ModelProviderEntity> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelProviderEntity::getModelType, "Plugin");
        List<ModelProviderEntity> providerEntities = modelProviderDao.selectList(queryWrapper);
        List<ModelProviderDTO> resultList = ConvertUtils.sourceToTarget(providerEntities, ModelProviderDTO.class);

        // 2. 获取当前用户的知识库列表并追加到结果中
        UserDetail userDetail = SecurityUser.getUser();
        if (userDetail != null && userDetail.getId() != null) {
            // 查询当前用户的知识库
            LambdaQueryWrapper<KnowledgeBaseEntity> kbQueryWrapper = new LambdaQueryWrapper<>();
            kbQueryWrapper.eq(KnowledgeBaseEntity::getCreator, userDetail.getId());
            kbQueryWrapper.eq(KnowledgeBaseEntity::getStatus, 1); // 只获取启用状态的知识库
            List<KnowledgeBaseEntity> knowledgeBases = knowledgeBaseDao.selectList(kbQueryWrapper);

            // 将知识库转换为ModelProviderDTO格式并添加到结果列表
            for (KnowledgeBaseEntity kb : knowledgeBases) {
                ModelProviderDTO dto = new ModelProviderDTO();
                dto.setId(kb.getId());
                dto.setModelType("Rag");
                dto.setName("[知识库]" + kb.getName());
                dto.setProviderCode("ragflow"); // 假设所有RAG都使用ragflow
                dto.setFields("[]");
                dto.setSort(0);
                dto.setCreateDate(kb.getCreatedAt());
                dto.setUpdateDate(kb.getUpdatedAt());
                dto.setCreator(0L);
                dto.setUpdater(0L);
                resultList.add(dto);
            }
        }

        return resultList;
    }

    /**
     * MCP 网关自动同步：请求 http://127.0.0.1:8123/list-tools，将返回的工具 UPSERT 到 ai_model_provider。
     * 连接失败或解析异常时仅打日志，不抛错（降级策略）。
     */
    @SuppressWarnings("unchecked")
    protected void syncMcpToolsToDb() {
        String url = mcpGatewayProperties.getListToolsUrl();
        if (StringUtils.isBlank(url)) {
            return;
        }
        try {
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            if (response.getBody() == null || !response.getStatusCode().is2xxSuccessful()) {
                log.warn("MCP 网关 list-tools 返回非 2xx: {}", url);
                return;
            }
            String body = response.getBody().trim();
            List<Map<String, Object>> rawTools = new ArrayList<>();
            if (body.startsWith("[")) {
                rawTools = JsonUtils.parseObject(body, new TypeReference<List<Map<String, Object>>>() {});
            } else if (body.startsWith("{")) {
                Map<String, Object> wrapper = JsonUtils.parseObject(body, new TypeReference<Map<String, Object>>() {});
                Object tools = wrapper != null ? wrapper.get("tools") : null;
                if (tools instanceof List) {
                    rawTools = (List<Map<String, Object>>) tools;
                }
            }
            if (rawTools == null || rawTools.isEmpty()) {
                return;
            }
            Date now = new Date();
            for (Map<String, Object> raw : rawTools) {
                String name = raw.get("name") != null ? raw.get("name").toString() : null;
                if (StringUtils.isBlank(name)) {
                    continue;
                }
                String title = raw.get("title") != null ? raw.get("title").toString().trim() : "";
                String description = raw.get("description") != null ? raw.get("description").toString() : "";
                Object inputSchemaObj = raw.get("input_schema");
                Map<String, Object> inputSchema = null;
                if (inputSchemaObj instanceof Map) {
                    inputSchema = (Map<String, Object>) inputSchemaObj;
                }
                List<Map<String, Object>> fieldsList = JsonSchemaToFieldsConverter.fromInputSchema(inputSchema);
                String fieldsJson = JsonSchemaToFieldsConverter.toFieldsJson(fieldsList);

                String id = Constant.MCP_PLUGIN_ID_PREFIX + name;
                String providerName = StringUtils.isNotBlank(title)
                        ? title
                        : (StringUtils.isNotBlank(description) ? description : name);
                if (providerName.length() > 50) {
                    providerName = providerName.substring(0, 50);
                }

                ModelProviderEntity entity = new ModelProviderEntity();
                entity.setId(id);
                entity.setModelType("Plugin");
                entity.setProviderCode("MCP");
                entity.setName(providerName);
                entity.setFields(fieldsJson);
                entity.setSort(0);
                entity.setCreator(0L);
                entity.setUpdater(0L);
                entity.setCreateDate(now);
                entity.setUpdateDate(now);

                ModelProviderEntity existing = modelProviderDao.selectById(id);
                if (existing != null) {
                    existing.setName(providerName);
                    existing.setFields(fieldsJson);
                    existing.setSort(0);
                    existing.setUpdater(0L);
                    existing.setUpdateDate(now);
                    modelProviderDao.updateById(existing);
                } else {
                    modelProviderDao.insert(entity);
                }
            }
            log.debug("MCP 网关同步完成，工具数: {}", rawTools.size());
        } catch (Exception e) {
            log.warn("MCP 网关同步失败，继续使用库内插件: {} - {}", url, e.getMessage());
        }
    }

    @Override
    public ModelProviderDTO getById(String id) {
        ModelProviderEntity entity = modelProviderDao.selectById(id);
        return ConvertUtils.sourceToTarget(entity, ModelProviderDTO.class);
    }

    @Override
    public List<ModelProviderDTO> getPluginListByIds(Collection<String> ids) {
        LambdaQueryWrapper<ModelProviderEntity> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.in(ModelProviderEntity::getId, ids);
        queryWrapper.eq(ModelProviderEntity::getModelType, "Plugin");
        List<ModelProviderEntity> providerEntities = modelProviderDao.selectList(queryWrapper);
        return ConvertUtils.sourceToTarget(providerEntities, ModelProviderDTO.class);
    }

    @Override
    public List<ModelProviderDTO> getListByModelType(String modelType) {

        QueryWrapper<ModelProviderEntity> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("model_type", StringUtils.isBlank(modelType) ? "" : modelType);
        List<ModelProviderEntity> providerEntities = modelProviderDao.selectList(queryWrapper);
        return ConvertUtils.sourceToTarget(providerEntities, ModelProviderDTO.class);
    }

    @Override
    public PageData<ModelProviderDTO> getListPage(ModelProviderDTO modelProviderDTO, String page, String limit) {

        Map<String, Object> params = new HashMap<String, Object>();
        params.put(Constant.PAGE, page);
        params.put(Constant.LIMIT, limit);
        params.put(Constant.ORDER_FIELD, List.of("model_type", "sort"));
        params.put(Constant.ORDER, "asc");

        IPage<ModelProviderEntity> pageParam = getPage(params, null, true);

        QueryWrapper<ModelProviderEntity> wrapper = new QueryWrapper<ModelProviderEntity>();

        if (StringUtils.isNotBlank(modelProviderDTO.getModelType())) {
            wrapper.eq("model_type", modelProviderDTO.getModelType());
        }

        if (StringUtils.isNotBlank(modelProviderDTO.getName())) {
            wrapper.and(w -> w.like("name", modelProviderDTO.getName())
                    .or()
                    .like("provider_code", modelProviderDTO.getName()));
        }
        return getPageData(modelProviderDao.selectPage(pageParam, wrapper), ModelProviderDTO.class);
    }

    public static void main(String[] args) {
        String jsonString = "\"[]\"";
        JSONArray jsonArray = new JSONArray(jsonString);
        System.out.println("字符串转 JSONArray: " + jsonArray.toString());
    }

    @Override
    public ModelProviderDTO add(ModelProviderDTO modelProviderDTO) {
        UserDetail user = SecurityUser.getUser();
        modelProviderDTO.setCreator(user.getId());
        modelProviderDTO.setUpdater(user.getId());
        modelProviderDTO.setCreateDate(new Date());
        modelProviderDTO.setUpdateDate(new Date());
        // 去除Fields左右的双引号

        modelProviderDTO.setFields(modelProviderDTO.getFields());
        ModelProviderEntity entity = ConvertUtils.sourceToTarget(modelProviderDTO, ModelProviderEntity.class);
        if (modelProviderDao.insert(entity) == 0) {
            throw new RenException(ErrorCode.ADD_DATA_FAILED);
        }

        return ConvertUtils.sourceToTarget(modelProviderDTO, ModelProviderDTO.class);
    }

    @Override
    public ModelProviderDTO edit(ModelProviderDTO modelProviderDTO) {
        UserDetail user = SecurityUser.getUser();
        modelProviderDTO.setUpdater(user.getId());
        modelProviderDTO.setUpdateDate(new Date());
        if (modelProviderDao
                .updateById(ConvertUtils.sourceToTarget(modelProviderDTO, ModelProviderEntity.class)) == 0) {
            throw new RenException(ErrorCode.UPDATE_DATA_FAILED);
        }
        return ConvertUtils.sourceToTarget(modelProviderDTO, ModelProviderDTO.class);
    }

    @Override
    public void delete(String id) {
        if (modelProviderDao.deleteById(id) == 0) {
            throw new RenException(ErrorCode.DELETE_DATA_FAILED);
        }
    }

    @Override
    public void delete(List<String> ids) {
        if (modelProviderDao.deleteBatchIds(ids) == 0) {
            throw new RenException(ErrorCode.DELETE_DATA_FAILED);
        }
    }

    @Override
    public List<ModelProviderDTO> getList(String modelType, String providerCode) {
        QueryWrapper<ModelProviderEntity> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("model_type", StringUtils.isBlank(modelType) ? "" : modelType);
        queryWrapper.eq("provider_code", StringUtils.isBlank(providerCode) ? "" : providerCode);
        List<ModelProviderEntity> providerEntities = modelProviderDao.selectList(queryWrapper);
        return ConvertUtils.sourceToTarget(providerEntities, ModelProviderDTO.class);
    }
}
