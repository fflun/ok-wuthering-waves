"""An active child owns its transaction journal until its bounded stage exits."""
from cloud_restart_resume import assert_controls

def check_controls(state, *, child_active=False):
    # User stop/pause remains effective during a child-owned transaction.
    if any((state/name).exists() for name in ('stop-request','pause-request')):
        raise RuntimeError('local_stop_request; restart cannot override it')
    # An idle boundary must reconcile every journal before another stage starts.
    # Native claim/food guards verify their own writes while the child is active;
    # killing that child merely because it wrote pending interrupts the receipt.
    if not child_active:
        assert_controls(state,[state])
