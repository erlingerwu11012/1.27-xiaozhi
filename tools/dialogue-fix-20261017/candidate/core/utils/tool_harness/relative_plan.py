"""Finish an already authorized relative-setting plan using its fresh read."""
from .models import Step


def complete_relative_plan(decision, adjustments, tools, query=''):
    if (decision.mode not in {'operate', 'continue'} or decision.intent != 'action'
            or len(decision.steps) != 1 or len(adjustments) > 1):
        return decision
    read = decision.steps[0]
    read_only=read.tool=='self_get_device_status' and not read.arguments and not read.depends_on
    if not read_only and read.tool not in {'self_audio_speaker_set_volume','self_screen_set_brightness'}:return decision
    if adjustments:
        tool, delta = next(iter(adjustments.items()))
    else:
        # The model has already named the single authorized target. Only fill
        # an explicit one-step relative amount, never infer a request from a
        # complaint or choose its target from a keyword.
        import re
        from .domains import bounds
        if len(decision.authorized_writes)!=1:return decision
        tool=decision.authorized_writes[0]
        if tool not in {'self_audio_speaker_set_volume','self_screen_set_brightness'} or tool not in tools:return decision
        matches=list(re.finditer(r'(?:再(?:调|放|变)?|调|放|变|降|提)(大|小|高|低|亮|暗)(?:声)?(?:一点|一些|点)',query))
        if len(matches)!=1 or re.search(r'(?:不要|不用|别|不想)(?:再)?(?:调|放|变|降|提)?(?:大|小|高|低|亮|暗)|如果|假如|解释|意思|到|成|为|至|\d',query):return decision
        delta=1 if tool=='self_screen_set_brightness' and bounds(tool,tools[tool])==(1,5) else 10
        if matches[0][1] in {'小','低','暗'}:delta=-delta
    if (tool not in {'self_audio_speaker_set_volume', 'self_screen_set_brightness'}
            or tool not in tools or set(decision.authorized_writes) != {tool}):
        return decision
    if not read_only:
        if read.tool!=tool:return decision
        # An explicit relative request cannot use a model-guessed absolute
        # value or default magnitude. The executor reads fresh state instead.
        read.arguments={};read.relative=delta;read.extreme=None
        decision.finished=True
        return decision
    # This is not an authorization shortcut: both the original read and appended
    # setting still pass normal evidence, schema, session, ledger and receipt gates.
    name = 'apply_relative' if read.id != 'apply_relative' else 'apply_relative_2'
    decision.steps.append(Step(id=name, tool=tool, arguments={}, relative=delta, depends_on=[read.id]))
    decision.finished = True
    return decision
