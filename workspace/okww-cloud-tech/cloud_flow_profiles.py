"""Read-only definitions for simple and full daily/weekly flows.

This module does not enable a scheduler or launch a game. Echo-only farming
is distinct from weekly material reward claims, which remain in both modes.
"""
from copy import deepcopy

from cloud_weekly_chain import plan_chain

MODES = ('simple', 'full')
ECHO_TARGETS = ('boss', 'nests', 'both')


def plan_flow(daily, weekly, mode='simple', echo_target='boss', now=None):
    if mode not in MODES:
        raise ValueError('Unknown flow mode')
    if echo_target not in ECHO_TARGETS:
        raise ValueError('Unknown echo target')
    result = deepcopy(plan_chain(daily, weekly, now))
    result.update(mode=mode, echo_target=echo_target if mode == 'full' else None,
                  plan_only=True, echo_autostart_enabled=False)
    # Weekly material claims use 90-level fights and remain in simple mode.
    for action in result['actions']:
        if action['stage'] == 'boss':
            action.update(purpose='weekly_material_rewards', level=90,
                          absorb_echo=False)
    if mode == 'full':
        # The weekly-only 90-minute limit is not acceptance for a longer flow.
        result['weekly_chain_scheduler_seconds'] = result['required_scheduler_seconds']
        result['required_scheduler_seconds'] = None
        result['scheduler_limit_needs_review'] = True
        action = 'blocked' if result['blocked'] else 'planned'
        if echo_target in ('boss', 'both'):
            result['actions'].append(dict(stage='boss_echo', action=action,
                purpose='target_boss_echo', rounds=20, level=80,
                absorb_echo=True, claim_stamina_rewards=False,
                yolo_fallback_seconds=10, estimated_minutes=[30, 40]))
        if echo_target in ('nests', 'both'):
            result['actions'].append(dict(stage='nest_echo', action=action,
                purpose='all_available_uncleared_nests', scope='live_catalog',
                absorb_echo=True, resume_pending_pickup_first=True,
                require_verified_absorption=True, claim_stamina_rewards=False,
                estimated_minutes=[20, 30],
                estimate_scope='previous five residual-discord nests only'))
    result['failure_policy'] = 'stop_and_notify_preserve_completed_progress'
    result['premium_currency_forbidden'] = True
    return result
