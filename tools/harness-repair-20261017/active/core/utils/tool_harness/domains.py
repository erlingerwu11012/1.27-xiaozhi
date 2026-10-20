"""Discontiguous brightness domain matching the deployed firmware contract."""
def level_capability(definition):
    description=definition.description['function'].get('description','')
    return '档' in description and ('1-5' in description or '1 到 5' in description or '1到5' in description)
def validate_domain(name,args,definition):
    if name=='habit_learn' and str(args.get('intent','')).strip().lower() in {'create','add','set','update','habit','create_habit','reminder','learn'}:raise ValueError('habit_intent_must_describe_actual_behavior_not_create_or_set')
    if name=='self_screen_set_brightness' and level_capability(definition):
        value=args.get('brightness')
        if type(value) is not int or not (1<=value<=5 or 50<=value<=100):raise ValueError('brightness_requires_level_1_5_or_percent_50_100')
def bounds(name,definition):
    if name=='self_screen_set_brightness' and level_capability(definition):return 1,5
    key='volume' if 'volume' in name else 'brightness'
    spec=definition.description['function']['parameters']['properties'][key]
    return spec.get('minimum'),spec.get('maximum')
