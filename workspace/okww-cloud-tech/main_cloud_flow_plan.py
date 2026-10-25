"""Print a flow profile without launching a browser or changing ledgers."""
import argparse
import json
from pathlib import Path

from cloud_autorun_state import DailyLedger
from cloud_flow_profiles import ECHO_TARGETS, MODES, plan_flow
from cloud_weekly_state import WeeklyLedger

ROOT = Path(__file__).resolve().parent
STATE = ROOT.parent / 'okww-cloud-session/background'
PROFILE = ROOT.parent.parent / 'configs/cloud-flow-profiles.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=MODES)
    parser.add_argument('--echo-target', choices=ECHO_TARGETS)
    args = parser.parse_args(argv)
    settings = json.loads(PROFILE.read_text(encoding='utf-8'))
    result = plan_flow(DailyLedger(STATE / 'daily-ledger.json'),
                      WeeklyLedger(STATE / 'weekly-ledger.json'),
                      mode=args.mode or settings['default_mode'],
                      echo_target=args.echo_target or settings['full']['echo_target'])
    config=json.loads((STATE / 'autorun-config.json').read_text(encoding='utf-8'))
    result['scheduled_mode']='full' if config.get('full_enabled') is True else 'daily_only'
    result['echo_autostart_enabled']=config.get('full_enabled') is True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
