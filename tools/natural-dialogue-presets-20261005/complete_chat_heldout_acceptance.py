"""Previously unused wording/topics, fixed before looking at model responses."""
import os
from pathlib import Path
scenarios=[
 ['新买的落地灯出了快递单号，但快递还没有收件。我只是闲聊，不用帮我安排。',
  '单号出来不代表灯已经在路上，你按这个理解。',
  '今天不想被调侃，也别总反问我。',
  '以前看灯只看亮不亮，现在也会在意它摆着好不好看。',
  '你觉得为什么同样亮度的灯，看着也能差这么多？',
  '顺便说下，之前买的椅子早就送到了，灯还没被快递收走，这两个别混了。',
  '刚收到更新，快递已经揽收了这盏灯，我本人还没收到。',
  '我说已经揽收，不是已经放到我客厅里了。',
  '只按我说过的消息，灯和椅子分别在哪个阶段？',
  '我没有告诉你客厅大小和灯放哪里，这些你也不知道，对吧？'],
 ['演示文稿一共十页，已经写了六页，后四页没写。先别教我怎么做。',
  '昨天只调整了第一页的排版，不是只写了第一页。',
  '别每句问我问题，正常聊两句就好。',
  '有些演示页面看着很热闹，实际一句重点都找不到。',
  '你说说这种页面为什么让人看着累，别给我制作步骤。',
  '纠正一下，六页是有占位文字的初稿，真正写好的正文只有两页。',
  '刚才那个六页完成的说法，我已经纠正了，现在别继续按六页写完理解。',
  '今天又写好一页正文，所以现在真正写好的有三页了。',
  '按最新情况，十页里真正写好几页，还剩几页？',
  '现在给我一个具体建议，先从剩下部分的哪一步开始？'],
 ['昨天加班挺烦的，我只想吐槽，别给方案也别教育我。',
  '反问也先停一下，直接聊你的看法。',
  '活儿其实不多，主要是一直等别人回消息。',
  '人忙完了又不能走，那种耗着的感觉更烦。',
  '你说说这种等待跟单纯忙有什么区别？',
  '换个话题，帮我解释一下摄影里的景深是什么意思，我不是让你拍照。',
  '现在问我一句吧，我想聊音乐。',
  '我最近常听钢琴曲，不过没有自己学钢琴。',
  '我还是想先听你的观点，不用继续提问。',
  '朋友说他周六想来看我，但没有确认会来。我也没准备饭，别补成饭做好了。'],
]
os.environ.setdefault('CHAT_REPORT','complete-chat-heldout')
os.environ['CHAT_MODELS']='qwen3.8-max'
os.environ['CHAT_SEMANTIC']='1'
source=Path(__file__).with_name('complete_chat_acceptance.py').read_text()
start=source.index('scenarios = [')
end=source.index('\nresult = ',start)
source=source[:start]+'scenarios = '+repr(scenarios)+'\nprofiles=[profiles[0],profiles[-1]]\n'+source[end:]
exec(compile(source,'<complete-chat-heldout>', 'exec'))
