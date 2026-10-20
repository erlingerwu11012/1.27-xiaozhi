from pathlib import Path
r=Path(__file__).resolve().parents[2]/'tmp/bailian-memory-product/server/main/manager-api/src/main/java/xiaozhi/modules/personmemory/RecentArchiveService.java'
t=r.read_text(encoding='utf-8')
t=t.replace('记得吗|有没有|是否|告诉我|请问|怎么|能不能|为什么','记得吗|有没有|是否|告诉我|请问|怎么|能不能|为什么|你觉得|猜猜|假如|如果|也许|可能|是不是')
start=t.index('        return text.matches("(?s).*(我叫');end=t.index('\n    }',start)
t=t[:start]+'        return text.codePointCount(0,text.length())>=4;'+t[end:]
t=t.replace('),terms)<2 ||', '),terms)<Math.min(2,terms.size()) ||')
r.write_text(t,encoding='utf-8')
