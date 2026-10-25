"""Read-only evidence around the native nightmare task; no input or decisions."""
import json
import time


def install(task, capture, output):
    import cv2
    output.mkdir(parents=True, exist_ok=True)
    events = output / 'nightmare-events.jsonl'
    events.write_text('', encoding='utf-8')

    def record(event, **values):
        with events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=time.time(), event=event, **values), ensure_ascii=False)+'\n')
        task.log_info(f'CLOUD_NIGHTMARE {event} {values}')

    original_frame = capture.do_get_frame
    last = [0]
    def frame():
        result = original_frame()
        if result is not None and time.monotonic()-last[0] >= 15:
            cv2.imwrite(str(output/'nightmare-current.png'), result)
            last[0] = time.monotonic()
        return result
    capture.do_get_frame = frame

    original_nest = task.combat_nest
    counter = [0]
    def nest(target):
        counter[0] += 1
        record('nest_start', attempt=counter[0], key=getattr(target, 'cache_key', None))
        try:
            result = original_nest(target)
        except Exception as exc:
            record('nest_error', attempt=counter[0], error=type(exc).__name__, message=str(exc))
            raise
        record('nest_return', attempt=counter[0], captured=bool(task._capture_success),
               skipped=sorted(task._unreachable_nests))
        return result
    task.combat_nest = nest

    original_revive = task.revive_action
    def revive():
        record('native_revive_start')
        result = original_revive()
        record('native_revive_return', success=bool(result))
        return result
    task.revive_action = revive
    record('observation_installed', quests=task.config.get('Which to Farm'))
