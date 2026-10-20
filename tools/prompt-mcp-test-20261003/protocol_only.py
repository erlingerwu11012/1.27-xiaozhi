"""Finish device dispatch tests offline, preserving real-model reports."""
from pathlib import Path

out_dir = Path('/root/prjs/tmp/prompt-mcp-test-20261003')
setup = (out_dir / 'run_test.py').read_text().split('messages_by_case={}')[0]
setup = setup.replace("'report.json'", "'complete-report.json'")
setup = setup.replace('gateway_tools = asyncio.run(inspect_live_mcp())',
                      "gateway_tools = json.loads((OUT / 'gateway-tools.json').read_text())")
exec(compile(setup, str(out_dir / 'run_test.py'), 'exec'))
report = json.loads((OUT / 'followup-report.json').read_text())
initial = json.loads((OUT / 'initial-report.json').read_text())
# The first automatic receipt check only matched Arabic HH:MM. Accept the
# equivalent spoken Chinese time, deriving it from the actual live receipt.
for row in report['continuations']:
    if row['case'] != 'world_time':
        continue
    body = report['live_mcp']['model_selected_execution']['result']
    receipt = '\n'.join(x.get('text', '') for x in body['content'] if x.get('type') == 'text')
    clock_match = re.search(r'(\d{2}):(\d{2}):\d{2}', receipt)
    def cn_number(number):
        digits = '零一二三四五六七八九'
        if number < 10: return digits[number]
        if number == 10: return '十'
        return (digits[number // 10] if number >= 20 else '') + '十' + (digits[number % 10] if number % 10 else '')
    hour, minute = map(int, clock_match.groups())
    spoken = cn_number(hour) + '点' + ('零' if 0 < minute < 10 else '') + cn_number(minute) + '分'
    row['first_literal_check_passed'] = row['passed']
    row['expected_live_time'] = clock_match[0]
    row['accepted_spoken_time'] = spoken
    row['passed'] = not row['calls'] and (clock_match[0] in row['text'] or spoken in row['text'])
    row['validation_note'] = 'Arabic or Chinese spoken HH:MM; no conversational-quality assertion'
followup = (OUT / 'followup_test.py').read_text()
exec(compile(followup[followup.index('class SyntheticSocket:'):],
             str(out_dir / 'followup_test.py'), 'exec'))
