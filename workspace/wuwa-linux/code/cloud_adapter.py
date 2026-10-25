"""Only install browser I/O recognition and the explicitly requested claim policy."""


def install(pending_path):
    from src.task.DailyTask import DailyTask
    from src.task.TacetTask import TacetTask
    from src.task.ForgeryTask import ForgeryTask
    from src.task.DomainTask import DomainTask
    from src.task.BaseCombatTask import BaseCombatTask
    from src.combat.CombatCheck import CombatCheck
    from src.char.Aemeath import Aemeath
    from src.char.Hiyuki import Hiyuki
    protected = [(DailyTask, 'run'), (TacetTask, 'farm_tacet'),
                 (ForgeryTask, 'farm_forgery'), (DomainTask, 'farm_in_domain'),
                 (DomainTask, 'farm_domain_with_recovery_loop'), (DomainTask, 'revive_action'),
                 (BaseCombatTask, 'combat_once'), (BaseCombatTask, '_choose_switch_target'),
                 (BaseCombatTask, 'get_current_con'), (CombatCheck, 'in_combat'),
                 (CombatCheck, 'do_check_in_combat'), (CombatCheck, 'target_enemy'),
                 (Aemeath, 'do_perform'), (Hiyuki, 'do_perform')]
    originals = {(owner, name): getattr(owner, name) for owner, name in protected}
    if any(not method.__module__.startswith('src.') for method in originals.values()):
        raise RuntimeError('Legacy combat patches detected: restart with a clean process')
    from cloud_loot import install as install_recognition
    from cloud_daily_policy import install as install_claim_policy
    install_recognition()
    install_claim_policy(pending_path)
    from cloud_concerto import install as install_concerto_color
    install_concerto_color()
    from cloud_combat_exit import install as install_exit_cleanup
    install_exit_cleanup()
    from cloud_echo_pickup import install as install_echo_pickup
    install_echo_pickup()
    if any(getattr(owner, name) is not method for (owner, name), method in originals.items()):
        raise RuntimeError('Cloud adapter changed a protected upstream method')
