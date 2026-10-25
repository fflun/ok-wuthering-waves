"""Explicit B/C daily-only context; never redirect the default A runner."""
import hashlib,json
from pathlib import Path
from cloud_accounts import account_paths,validate_registry,verify_account_identity
from cloud_autorun_state import write_json

def resolve_context(root,account):
    state=Path(root).resolve().parent/'okww-cloud-session/background'
    registry=json.loads((state/'accounts/registry.json').read_text(encoding='utf-8'))
    validate_registry(registry,state)
    p=account_paths(state,account)
    settings=json.loads(p.config.read_text(encoding='utf-8'))
    if account not in ('b','c') or settings.get('account_id')!=account:
        raise ValueError('Only explicit small-account contexts are supported')
    if (settings.get('mode')!='daily_only' or settings.get('allowed_stages')!=['daily']
            or settings.get('weekly',{}).get('enabled') is not False
            or settings.get('echo',{}).get('enabled') is not False
            or settings.get('allow_premium_stamina') is not False):
        raise ValueError('Small account must be daily-only without premium spending')
    return p,settings

def verify_or_bind(root,account,uid,allow_bind=False):
    state=Path(root).resolve().parent/'okww-cloud-session/background'
    path=state/'accounts/registry.json'
    registry=json.loads(path.read_text(encoding='utf-8'))
    validate_registry(registry,state)
    item=next(a for a in registry['accounts'] if a['id']==account)
    if item['expected_uid_hash'] is None:
        if not allow_bind:raise RuntimeError('Account UID binding required')
        if not isinstance(uid,str) or len(uid)!=9 or not uid.isascii() or not uid.isdigit():
            raise ValueError('Invalid observed UID')
        digest=hashlib.sha256(uid.encode()).hexdigest()
        if any(a.get('expected_uid_hash')==digest for a in registry['accounts']):
            raise RuntimeError('This UID already belongs to another slot')
        item.update(expected_uid_hash=digest,binding_status='verified_in_owned_profile')
        validate_registry(registry,state)
        write_json(path,registry)
    verify_account_identity(registry,account,uid)

def install_daily_capture_confirmation(task,account):
    if account not in ('b','c'):raise ValueError('Daily capture confirmation is B/C only')
    native_nest=task.combat_nest
    native_notification=task.has_echo_notification
    observed=False
    def notification():
        nonlocal observed
        if not getattr(task,'_cloud_daily_capture_active',False):return native_notification()
        if observed:return True
        # Upstream also sets this flag when combat returned without a drop.
        # A fresh notification read must not inherit that cached guess.
        task._capture_success=False
        observed=bool(native_notification())
        task._capture_success=observed
        return observed
    def nest(target):
        nonlocal observed
        if not getattr(task,'_cloud_daily_capture_active',False):return native_nest(target)
        observed=False;task._capture_success=False
        result=native_nest(target)
        if not observed:
            def fresh():
                task.next_frame()
                return notification()
            task.wait_until(fresh,time_out=2,raise_if_not_found=False)
        task._capture_success=observed
        if not observed and getattr(target,'cache_key',None):
            task._unreachable_nests.add(target.cache_key)
            task.log_info('CLOUD_DAILY_ECHO no notification; skip this candidate for current capture run')
        return result
    task.has_echo_notification=notification
    task.combat_nest=nest

def install_daily_capture_combat(task,account):
    if account not in ('b','c'):raise ValueError('Daily capture combat is B/C only')
    native=task.in_combat
    def combat(*args,**kwargs):
        result=native(*args,**kwargs)
        if result or not getattr(task,'_cloud_daily_capture_active',False):return result
        if getattr(task,'_capture_success',False):return result
        task.next_frame()
        ok,index,count=task.in_team()
        health=task.has_health_bar()
        import re
        objective=task.ocr(.005,.18,.29,.46,match=re.compile(
            r'清剿残[象像]聚落|清理聚落中的残[象像]|梦魇拔除|夢魘拔除|已击败残[象像]'))
        names=[b.name for b in objective]
        positive=bool(ok and count==3 and health and names)
        import os,time,cv2
        folder=os.environ.get('OKWW_DAILY_OUTPUT')
        if folder and (positive or not getattr(task,'_cloud_daily_enemy_negative_saved',False)):
            cv2.imwrite(str(Path(folder)/f'{time.time_ns()}-daily-echo-enemy-evidence.png'),task.frame)
            task.log_info(f'CLOUD_DAILY_ECHO enemy evidence team={ok}/{count} health={health} objective={names} accepted={positive}')
            task._cloud_daily_enemy_negative_saved=True
        if not positive:return result
        task._in_combat=True
        return task.scene.set_in_combat()
    task.in_combat=combat

def install_daily_capture_entry(task,account):
    if account not in ('b','c'):raise ValueError('Daily capture entry is B/C only')
    native_capture=task.run_capture_mode
    # DailyTask temporarily overrides this instance method with a no-op.
    # Preserve the class implementation for the initial world preparation.
    world_prepare=type(task).ensure_main.__get__(task,type(task))
    def capture():
        # Native capture may reopen the book after an unreachable target.
        # Keep its class world recovery active for this bounded daily capture.
        missing=object()
        prior=task.__dict__.get('ensure_main',missing)
        task.ensure_main=world_prepare
        task._cloud_daily_capture_active=True
        try:
            world_prepare(time_out=30)
            task.next_frame()
            if not task.in_world():
                raise RuntimeError('Daily echo world entry unverified; no book clicks')
            from cloud_revive import recovery_navigation,world_heal_and_reenter
            with recovery_navigation(task):
                world_heal_and_reenter(task,reenter=False)
            task.log_info('CLOUD_DAILY_ECHO three slots verified full before native capture')
            return native_capture()
        finally:
            task._cloud_daily_capture_active=False
            if prior is missing:task.__dict__.pop('ensure_main',None)
            else:task.ensure_main=prior
    task.run_capture_mode=capture

def configure_daily(tasks,settings):
    daily=tasks['daily']
    if settings.get('cultivation_target') in ('forgery_first','recommended_weapon_skill'):
        daily.config['Which to Farm']='Forgery Challenge'
        daily.config['Which Forgery Challenge to Farm']=1
    if settings.get('cultivation_target')=='recommended_weapon_skill':
        from cloud_cultivation import enter_recommended,install_start_recovery
        tasks['forgery'].teleport_into_domain=lambda *a,**kw:enter_recommended(tasks['forgery'])
        tasks['forgery']._cloud_small_account=True
        install_start_recovery(tasks['forgery'])
    daily.config['Additional Tasks to Run After Daily Task']=[]
    daily.config['Farm Nightmare Nest for Daily Echo']=True
    install_daily_capture_entry(tasks['nightmare'],settings['account_id'])
    install_daily_capture_combat(tasks['nightmare'],settings['account_id'])
    install_daily_capture_confirmation(tasks['nightmare'],settings['account_id'])
    daily.char_config['Chisa DPS']=False
    for name in ('forgery','simulation','tacet'):
        tasks[name]._cloud_allow_solvent_entry=settings.get('allow_solvent') is True
        tasks[name]._cloud_claim_multiplier=settings.get('reward_multiplier') or 2
    if settings.get('allow_solvent') is not True:
        import cloud_daily_policy
        def refuse_refill(*args,**kwargs):
            raise RuntimeError('Small-account stamina refill is disabled; no materials consumed')
        cloud_daily_policy.refill=refuse_refill
