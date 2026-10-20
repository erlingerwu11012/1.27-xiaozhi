from pathlib import Path
R=Path(__file__).parent
p=R/'java/RecentArchiveService.java';s=p.read_text(encoding='utf-8-sig').replace('"什么","记得"','"我的","你的","我喝","你喝","现在","记忆","说过","提过","知道","还有","什么","记得"').replace('score(value,terms)<Math.min(2,terms.size())','score(value,terms)<1');p.write_text(s,encoding='utf-8')
p=R/'run_java_tests.py';s=p.read_text(encoding='utf-8-sig').replace('history(a,"coffee",1,"我喜欢咖啡",null,now-10);history', 'history(a,"coffee",1,"我喜欢咖啡",null,now-10);assertTrue(new RecentArchiveService(jdbc,memory,identities).search(a,"我喝咖啡吗").get("text").toString().contains("我喜欢咖啡"));history');p.write_text(s,encoding='utf-8')
