from pathlib import Path
S=Path('tools/experience-repair-20261009');p=S/'candidate/core/api/vision_handler.py';s=p.read_text(encoding='utf-8-sig');s=s.replace('            result = vllm.response(rebuilt_question, image_base64)', '''            try:
                timeout=max(1,min(60,float((current_config.get('server') or {}).get('vision_model_timeout_seconds',30))))
                result=await asyncio.wait_for(asyncio.to_thread(vllm.response,rebuilt_question,image_base64),timeout)
            except asyncio.TimeoutError:
                raise VisionRequestError(504,'upstream_timeout') from None
            if not isinstance(result,str) or not result.strip():
                raise VisionRequestError(502,'upstream_invalid_response')''',1)
# asyncio was previously imported only by a helper? Make the dependency explicit.
if 'import asyncio' not in s.split('class VisionHandler')[0]:s='import asyncio\n'+s
p.write_text(s,encoding='utf-8')
p=S/'package_candidate.py';s=p.read_text(encoding='utf-8').replace("names=['core/utils/device_reminder.py'", "names=['core/api/vision_handler.py','core/utils/device_reminder.py'",1);p.write_text(s,encoding='utf-8')
