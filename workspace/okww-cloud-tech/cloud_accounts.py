"""Offline multi-account configuration and isolated ledger paths.

No browser imports, login operations, game tasks or scheduler installation.
Account A references existing state in place; new accounts never copy cookies.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from cloud_autorun_state import DailyLedger
from cloud_full_chain import FullLedger
from cloud_weekly_state import WeeklyLedger

ACCOUNT_IDS=('a','b','c')


@dataclass(frozen=True)
class AccountPaths:
    account_id: str
    root: Path
    state: Path
    profile: Path
    config: Path
    runtime_config: Path
    pending_claim: Path
    logs: Path
    global_lock: Path

    def ledgers(self):
        return {'daily':DailyLedger(self.state/'daily-ledger.json'),
                'weekly':WeeklyLedger(self.state/'weekly-ledger.json'),
                'full':FullLedger(self.state/'full-ledger.json')}


def account_paths(background,account_id):
    if account_id not in ACCOUNT_IDS:raise ValueError('Unknown account slot')
    background=Path(background).resolve()
    root=background/'accounts'/account_id
    legacy=account_id=='a'
    return AccountPaths(account_id,root,background if legacy else root/'state',
        background/'game-profile' if legacy else root/'browser-profile',
        root/'settings.json',background.parent/'daily-config' if legacy else root/'runtime-config',
        background.parent/'claim-pending.json' if legacy else root/'state/claim-pending.json',
        background.parent/'daily-logs' if legacy else root/'logs',background/'runner.lock')


def registry_template(background,current_account_hash=None):
    registry={'version':1,'enabled':False,'runtime_integration':'not_implemented',
        'execution':'sequential','max_parallel':1,'order':list(ACCOUNT_IDS),
        'timezone':'Asia/Hong_Kong','daily_refresh':'04:00','weekly_refresh':'MON 04:00',
        'session_policy':'separate_profiles_close_without_logout','accounts':[]}
    for account_id in ACCOUNT_IDS:
        paths=account_paths(background,account_id)
        registry['accounts'].append({'id':account_id,'label':f'账号 {account_id.upper()}',
            'enabled':False,'profile':str(paths.profile),'settings':str(paths.config),
            'expected_uid_hash':current_account_hash if account_id=='a' else None,
            'binding_status':'existing_verified' if account_id=='a' and current_account_hash else 'not_bound'})
    validate_registry(registry,background)
    return registry


def validate_registry(registry,background):
    if registry.get('version')!=1:raise ValueError('Unsupported account registry')
    if registry.get('enabled') is not False or registry.get('runtime_integration')!='not_implemented':
        raise ValueError('Multi-account runtime is not enabled by this offline module')
    if registry.get('execution')!='sequential' or registry.get('max_parallel')!=1:
        raise ValueError('Concurrent game instances have not been validated')
    if registry.get('order')!=list(ACCOUNT_IDS):raise ValueError('Expected three ordered slots')
    accounts=registry.get('accounts',[])
    if len(accounts)!=3 or {a.get('id') for a in accounts}!=set(ACCOUNT_IDS):raise ValueError('Invalid slots')
    profiles=set();identities=set()
    for account in accounts:
        expected=account_paths(background,account['id'])
        assert_private_paths(background, expected)
        profile=Path(account['profile']).resolve()
        if profile!=expected.profile.resolve() or Path(account['settings']).resolve()!=expected.config.resolve():
            raise ValueError('Account paths may not be shared or redirected')
        if profile in profiles:raise ValueError('Shared browser profile forbidden')
        profiles.add(profile)
        if account.get('enabled') is not False:raise ValueError('Account slot is offline only')
        identity=account.get('expected_uid_hash')
        if identity is not None:
            if not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('Expected SHA256 UID binding')
            if identity in identities:raise ValueError('The same game account cannot occupy two slots')
            identities.add(identity)
    return registry


def assert_private_paths(background, paths):
    """Reject links/junctions that make an apparently separate slot share data."""
    background=Path(background).resolve()
    targets=(paths.root,paths.profile,paths.state,paths.config,paths.runtime_config,
             paths.pending_claim,paths.logs)
    for target in targets:
        current=target
        # A has two legacy paths immediately outside background.
        boundary=background.parent
        if not current.is_relative_to(boundary):
            raise ValueError('Account data escaped its session directory')
        while current!=boundary:
            if current.is_symlink() or current.is_junction():
                raise ValueError('Account data may not use links or junctions')
            current=current.parent


def isolation_manifest(background, account_id):
    """A resource contract, not an enabled browser/task transport.

    B/C transports must consume all these resources explicitly. Never fall back
    to A's constants when a profile, UID, target or endpoint is missing.
    """
    p=account_paths(background,account_id)
    assert_private_paths(background,p)
    index=ACCOUNT_IDS.index(account_id)
    files={name:str(p.state/filename) for name,filename in {
        'daily':'daily-ledger.json','weekly':'weekly-ledger.json',
        'full':'full-ledger.json','food':'food-receipt.json',
        'stop':'stop-request','status':'autorun-status.json',
        'notifications':'notifications.json','process':'owned-process.json',
        'browser_lock':'browser.lock','control_token':'control-token.local',
    }.items()}
    files['pending_claim']=str(p.pending_claim)
    return {'version':1,'account_id':account_id,'enabled':False,
        'runtime_integration':'not_implemented',
        'profile':str(p.profile),'config':str(p.config),
        'runtime_config':str(p.runtime_config),'logs':str(p.logs),
        'screenshots':str(Path(background).resolve().parent/'daily-screenshots'
                          if account_id=='a' else p.root/'screenshots'),
        'files':files,'progress_namespace':str(p.state),
        'reserved_endpoints':{'host':'127.0.0.1','bridge_port':19876+index,
                              'viewer_port':17867+index,'cdp':'owned_pipe_only'},
        'endpoint_status':'reserved_not_listening' if index else 'legacy_reference',
        'identity_policy':'verify_bound_uid_before_task_or_claim',
        'browser_policy':{'copy_login_data':False,'chrome_sync':False,
            'fallback_to_other_account':False,'shared_iab_tabs':False,
            'close_scope':'owned_process_tree_only'},
        'global_execution_lock':str(p.global_lock)}


def verify_account_identity(registry, account_id, observed_uid):
    """No raw UID is persisted. A mismatch must never rebind a running task."""
    if account_id not in ACCOUNT_IDS:raise ValueError('Unknown account slot')
    if not isinstance(observed_uid,str) or not re.fullmatch(r'\d{9}',observed_uid):
        raise ValueError('A stable nine-digit UID is required')
    accounts=registry.get('accounts',[])
    matches=[a for a in accounts if a.get('id')==account_id]
    if len(matches)!=1:raise ValueError('Invalid account slot')
    expected=matches[0].get('expected_uid_hash')
    if not expected:raise ValueError('Account has not been bound')
    actual=hashlib.sha256(observed_uid.encode('utf-8')).hexdigest()
    if actual!=expected:raise ValueError('Wrong account; stop without switching or rebinding')
    if any(a.get('id')!=account_id and a.get('expected_uid_hash')==actual for a in accounts):
        raise ValueError('Duplicate account binding')
    return True


def settings_template(account_id):
    if account_id not in ACCOUNT_IDS:raise ValueError('Unknown account slot')
    return {'version':1,'account_id':account_id,'enabled':False,
        'mode':'inherit_existing' if account_id=='a' else 'simple',
        'inherit_current_configuration':account_id=='a',
        'cultivation_target':None,'team':None,'reward_multiplier':None,
        'daily_required':['stamina_task','activity_rewards','mail','radio_tasks','radio_unlocked_rewards'],
        'allow_solvent':None if account_id=='a' else False,'allow_premium_stamina':False,
        'weekly':{'inherit_existing':account_id=='a','boss_materials':None,'garden':None},
        'echo':{'inherit_existing':account_id=='a','boss_rounds':None,'all_nests':None,'food':None},
        'failure_policy':'bounded_retry_then_stop_queue_and_notify',
        'setup_status':'reference_existing' if account_id=='a' else 'needs_login_binding_and_task_preferences'}


def write_initial_configuration(background,current_account_hash=None):
    """Write disabled configuration only. Never touch existing profiles/ledgers."""
    background=Path(background).resolve()
    registry=registry_template(background,current_account_hash)
    files={background/'accounts/registry.json':registry}
    files.update({account_paths(background,k).config:settings_template(k) for k in ACCOUNT_IDS})
    if any(path.exists() for path in files):raise FileExistsError('Existing account configuration must be reviewed, not overwritten')
    for path,data in files.items():
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
    return registry
