"""Linux regression selection with explicit nonportable fixture exclusions."""
import unittest,json
from pathlib import Path
excluded={
 'test_launcher_resume_history_remains_serializable_and_does_not_alias_previous':'External Windows one-off launcher is not part of deployed program',
 'test_queue_matches_parent_bound':'External Windows one-off launcher is not part of deployed program',
 'test_known_claimed_frame_and_missing_marker':'Historical full-account screenshot is outside source fixtures',
 'test_finished_today_never_launches_game_with_local_only':'Windows notification channel test; Linux must reject local-only notification',
 'test_local_only_readiness_and_missing_channel':'Windows notification channel test; Linux must reject local-only notification',
}
def visit(suite):
 for item in suite:
  if isinstance(item,unittest.TestSuite):yield from visit(item)
  else:yield item
suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent/'tests'),pattern='test_cloud*.py')
for case in visit(suite):
 reason=excluded.get(case._testMethodName)
 if reason:
  method=getattr(type(case),case._testMethodName)
  setattr(type(case),case._testMethodName,unittest.skip(reason)(method))
result=unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
from cloud_failure_notice import notification_ready
assert not notification_ready({'local_enabled':True}), 'Linux must not treat Windows toast as working alert'
print(json.dumps({'passed':result.testsRun-len(result.skipped),'skipped':len(result.skipped),'exclusions':excluded}))
