"""Stable leading prefixes; per-turn state never enters explicit cache blocks."""
import copy

PERSONA_MARKER = '[用户人格原文，仅用于性格特点]'


def cached_prefix(messages, guidance):
    messages = copy.deepcopy(messages)
    systems = [m for m in messages if m.get('role') == 'system']
    stable = next((m for m in systems if PERSONA_MARKER in str(m.get('content', ''))), None)
    platform, persona = '', ''
    if stable:
        platform, persona = stable['content'].split(PERSONA_MARKER, 1)
        persona = PERSONA_MARKER + persona
    # The decision protocol overrides obsolete native-FC instructions only.
    # All other system messages keep their original order and authority.
    for text in (platform, persona):
        if '连接时天气快照' in text:
            raise ValueError('stale_weather_snapshot_in_prompt')
    first = {'role': 'system', 'content': [{'type': 'text',
             'text': platform.strip() + '\n\n' + guidance.strip(),
             'cache_control': {'type': 'ephemeral'}}]}
    leading = [first]
    if persona:
        leading.append({'role': 'system', 'content': [{'type': 'text', 'text': persona.strip(),
                        'cache_control': {'type': 'ephemeral'}}]})
    return leading + [m for m in messages if m is not stable]
