from pathlib import Path
S=Path(__file__).resolve().parent
p=S/'work/core/providers/tools/server_plugins/plugin_executor.py';p.parent.mkdir(parents=True,exist_ok=True)
p.write_text((S/'plugin_executor.original.py').read_text(encoding='utf-8').replace('["memory_search","memory_forget","memory_correct"]','["memory_search","memory_add","memory_forget","memory_correct"]'),encoding='utf-8')
p=S/'java/PersonMemoryController.java';s=p.read_text(encoding='utf-8');anchor='    @PostMapping("/internal/material")';assert anchor in s
s=s.replace(anchor,'''    @Data public static class AddRequest {
        @NotNull @Valid private PersonTurnDTO actor;
        @NotBlank @Size(max=1024) private String fact;
    }
    @PostMapping("/internal/add")
    public Result<Map<String,Object>> add(@Valid @RequestBody AddRequest request) {
        return new Result<Map<String,Object>>().ok(service.add(request.getActor(),request.getFact()));
    }
'''+anchor);p.write_text(s,encoding='utf-8')
p=S/'java/PersonMemoryService.java';s=p.read_text(encoding='utf-8');anchor='    private void ensureEntity(PersonTurnDTO actor) {';assert anchor in s
s=s.replace(anchor,'''    @Transactional
    public Map<String,Object> add(PersonTurnDTO actor,String fact) {
        identities.lock(actor.getAccountId());validateActor(actor,false);
        if(fact==null || fact.isBlank() || fact.length()>1024 || !RecentArchiveService.factualUser(fact,1) || !fact.strip().equals(RecentArchiveService.normalizeFact(fact)))throw new RenException("只能保存明确的单条事实");
        String normalized=fact.strip();
        boolean cloud="matched".equals(actor.getStatus()) && enabled && "Memory_bailian".equals(jdbc.queryForObject("SELECT mem_model_id FROM ai_agent WHERE id=? AND user_id=?",String.class,actor.getAgentId(),actor.getAccountId()));
        if(cloud)ensureEntity(actor);
        String event=MemoryGatewayClient.sha("explicit-fact:"+actor.getTurnId());
        jdbc.update("INSERT IGNORE INTO ai_person_material(account_id,user_id,generation,agent_id,device_id,event_id,turn_id,kind,content,user_tokens,token_version) VALUES(?,?,?,?,?,?,?,'explicit_fact',?,?,1)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),actor.getDeviceId(),event,actor.getTurnId(),normalized,MemoryMaterialPolicy.userTokens(normalized));
        var rows=jdbc.queryForList("SELECT id,content,recall_allowed FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND event_id=? AND agent_id=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),event,actor.getAgentId());
        if(rows.size()!=1 || !normalized.equals(rows.get(0).get("content")) || !Boolean.TRUE.equals(rows.get(0).get("recall_allowed")))throw new RenException("该请求已变化或保存状态未确认");
        return Map.of("local_applied",true,"operation","add","status","completed","record_id","material:"+rows.get(0).get("id"),"version",MemoryGatewayClient.sha(normalized),"fact",normalized,"cloud_sync",cloud?"pending":"disabled");
    }

'''+anchor);p.write_text(s,encoding='utf-8')
p=S/'java/RecentArchiveService.java';s=p.read_text(encoding='utf-8')
s=s.replace("AND kind='dialogue'\";","AND kind IN('dialogue','explicit_fact')\";")
s=s.replace("AND kind='dialogue' AND turn_id<>?", "AND (kind='explicit_fact' OR kind='dialogue' AND turn_id<>?)")
p.write_text(s,encoding='utf-8')
p=S/'java/MemoryDailyWorker.java';s=p.read_text(encoding='utf-8')
s=s.replace("IN('dialogue','dialogue_assistant'", "IN('explicit_fact','dialogue','dialogue_assistant'")
s=s.replace('filter(m->"dialogue".equals(m.get("kind")))','filter(m->Set.of("dialogue","explicit_fact").contains(m.get("kind")))')
p.write_text(s,encoding='utf-8')
print('memory backend edits prepared')
