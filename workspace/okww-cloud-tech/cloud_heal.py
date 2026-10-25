"""Browser-only healing navigation; no changes to combat or claim decisions."""
import json
import os
import re
import urllib.error
import urllib.request

TRAVEL = re.compile(r'^(传送|傳送|快速旅行|Teleport|Fast Travel)$', re.I)


def map_selector(boxes):
    titles=[b for b in boxes if b.name.strip()=='切换地图'
            and 680<=b.x<=1000 and 15<=b.y<=75]
    regions={b.name.strip() for b in boxes if 690<=b.x<=925 and 80<=b.y<=520}
    return len(titles)==1 and len(regions & {'罗伊冰原','黎那汐塔','黑海岸','瑝珑','今州','梦州'})>=2


def close_map_selector(task):
    task.next_frame()
    if not map_selector(task.ocr(.50,0,1,.80)):return False
    task.sleep(.3)
    task.next_frame()
    if not map_selector(task.ocr(.50,0,1,.80)):
        raise RuntimeError('Cloud healing: map selector changed before cancellation')
    task.log_info('CLOUD_HEAL close positively verified map selector once')
    task.send_key('esc',after_sleep=.5)
    return True


def candidates(task):
    # Search the map including its lower edge; exclude UI overlays by position.
    # A real waypoint can sit underneath the top-left legend and be unclickable.
    area = task.box_of_screen(.10, .10, .93, .93)
    hits = []
    for name in ('map_way_point', 'map_way_point_big'):
        for box in task.find_feature(name, box=area, threshold=.70):
            x=(box.x+box.width/2)/task.frame.shape[1]
            y=(box.y+box.height/2)/task.frame.shape[0]
            if (x < .27 and y < .30) or (x < .24 and y > .85) or (x > .76 and y > .87):
                continue
            if not any(abs(box.x-old.x) < 15 and abs(box.y-old.y) < 15 for old in hits):
                hits.append(box)
    return sorted(hits, key=lambda b: b.confidence, reverse=True)


def travel_button(task):
    hits = task.ocr(.65, .75, .99, .98, match=TRAVEL)
    # Do not accept an ambiguous menu or an arbitrary template match.
    return hits[0] if len(hits) == 1 else None


def rewind_city_regions(task, boxes):
    """Scroll once only on the verified Jinzhou region list, never select unseen text."""
    expected={'荒石高地','归墟港市','无光之森','无明湾','北落野','怨鸟泽','虎口山脉','乘霄山'}
    def signature(values):
        if not map_selector(values) or any(b.name.strip()=='今州城' for b in values):return None
        # OCR can alternate 脈/脉 on the same saved map. Normalize this known
        # glyph only; different regions and unknown labels remain rejected.
        names={b.name.strip().replace('脈','脉') for b in values if 950<=b.x<=1200 and 80<=b.y<=590}
        return names & expected if len(names & expected)>=2 else None
    before=signature(boxes)
    if before is None:return False
    task.sleep(.3);task.next_frame()
    if signature(task.ocr(.50,0,1,.80))!=before:
        raise RuntimeError('Cloud healing: city list changed before scroll')
    task.log_info('CLOUD_HEAL verified Jinzhou region list; one scroll toward top')
    task.swipe_relative(.86,.21,.86,.72,duration=.6)
    task.sleep(.5)
    return True


def select_huanglong_regions(task, boxes):
    """Select only the named, twice observed country in the open map menu."""
    def target(values):
        if not map_selector(values):return None
        regions={b.name.strip().replace('脈','脉') for b in values
                 if 950<=b.x<=1200 and 80<=b.y<=590}
        if '今州城' in regions or len(regions & {'荒石高地','归墟港市','无光之森','无明湾','北落野','怨鸟泽','虎口山脉','乘霄山'})>=2:
            return None
        hits=[b for b in values if b.name.strip()=='瑝珑'
              and 690<=b.x<=925 and 80<=b.y<=590]
        return hits[0] if len(hits)==1 else None
    first=target(boxes)
    if first is None:return False
    task.sleep(.3);task.next_frame()
    second=target(task.ocr(.50,0,1,.80))
    if second is None or abs(first.x-second.x)>6 or abs(first.y-second.y)>6:
        raise RuntimeError('Cloud healing: named country changed before selection')
    task.log_info('CLOUD_HEAL verified named Huanglong country; fresh city and waypoint still required')
    task.click_box(second,after_sleep=.5)
    return True


def select_jinzhou_subregion(task, boxes):
    """Expanded country menus may require the named Jinzhou subregion."""
    def target(values):
        if not map_selector(values):return None
        if not any(b.name.strip()=='瑝珑' and 690<=b.x<=925 and 80<=b.y<=590 for b in values):return None
        if any(b.name.strip()=='今州城' and 950<=b.x<=1200 for b in values):return None
        hits=[b for b in values if b.name.strip()=='今州'
              and 690<=b.x<=925 and 80<=b.y<=590]
        return hits[0] if len(hits)==1 else None
    first=target(boxes)
    if first is None:return False
    task.sleep(.3);task.next_frame()
    second=target(task.ocr(.50,0,1,.80))
    if second is None or abs(first.x-second.x)>6 or abs(first.y-second.y)>6:
        raise RuntimeError('Cloud healing: named Jinzhou subregion changed before selection')
    task.log_info('CLOUD_HEAL verified named Jinzhou subregion; fresh city and waypoint still required')
    task.click_box(second,after_sleep=.5)
    return True


def city_waypoints(task):
    """One verified map-menu fallback when the native search shows no anchors."""
    def switch_button():
        task.next_frame()
        boxes=task.ocr(.72,.88,.95,.99,match=re.compile(r'^切换地图$'))
        return boxes[0] if len(boxes)==1 else None
    if switch_button() is None:return []
    task.sleep(.3)
    button=switch_button()
    if button is None:
        raise RuntimeError('Cloud healing: map switch changed before click')
    task.click_box(button,after_sleep=.5)
    last_boxes=[]
    def city():
        nonlocal last_boxes
        task.next_frame()
        boxes=task.ocr(.50,0,1,.80)
        last_boxes=boxes
        if not map_selector(boxes):return None
        hits=[b for b in boxes if b.name.strip()=='今州城'
              and 950<=b.x<=1200 and 80<=b.y<=180]
        return hits[0] if len(hits)==1 else None
    button=task.wait_until(city,time_out=5,raise_if_not_found=False)
    if button is None and rewind_city_regions(task,last_boxes):
        button=task.wait_until(city,time_out=5,raise_if_not_found=False)
    if button is None and select_huanglong_regions(task,last_boxes):
        button=task.wait_until(city,time_out=5,raise_if_not_found=False)
    if button is None and select_jinzhou_subregion(task,last_boxes):
        button=task.wait_until(city,time_out=5,raise_if_not_found=False)
        if button is None and rewind_city_regions(task,last_boxes):
            button=task.wait_until(city,time_out=5,raise_if_not_found=False)
    if button is None:
        raise RuntimeError('Cloud healing: Jinzhou city not positively available')
    task.sleep(.3)
    button=city()
    if button is None:
        raise RuntimeError('Cloud healing: city selection changed before click')
    task.log_info('CLOUD_HEAL verified Jinzhou city map fallback; no teleport yet')
    task.click_box(button,after_sleep=.5)
    def fresh_candidates():
        task.next_frame()
        return candidates(task)
    return task.wait_until(fresh_candidates,time_out=8,raise_if_not_found=False) or []


def choose_recovery(options, request=None):
    """One bounded text-only Flash request. Never execute model code/coordinates."""
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DeepSeek healing recovery unavailable: missing API key')
    payload = dict(model='deepseek-flash', max_tokens=256,
                   response_format={'type': 'json_object'},
                   messages=[dict(role='system', content=(
                       'You select one locally detected game-map waypoint after a failed healing teleport. '
                       'Return JSON only: {"candidate_id": integer or null}. '
                       'Select only an id from the provided list; null means stop. '
                       'You cannot issue commands, coordinates, purchases, combat inputs, or code edits.')),
                       dict(role='user', content=json.dumps({'stage': 'healing_waypoint_failed', 'candidates': options}))])
    req = urllib.request.Request('https://api.deepseek.com/chat/completions',
        data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    try:
        with (request or urllib.request.urlopen)(req, timeout=15) as response:
            data = json.load(response)
        decision = json.loads(data['choices'][0]['message']['content'])
        if set(decision) != {'candidate_id'}:
            raise ValueError('unexpected fields')
        selected = decision['candidate_id']
        if type(selected) is not int or selected not in {o['id'] for o in options}:
            raise ValueError('no allowed candidate selected')
        return selected
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'DeepSeek healing recovery HTTP {exc.code}; stopping') from None
    except Exception as exc:
        # Do not persist credentials, response bodies, or free-form model output.
        raise RuntimeError(f'DeepSeek healing recovery rejected ({type(exc).__name__}); stopping') from None


def attempt(task, waypoint):
    task.log_info(f'CLOUD_HEAL waypoint={waypoint}')
    task.click(waypoint, after_sleep=1)
    button = task.wait_until(lambda: travel_button(task), time_out=5, raise_if_not_found=False)
    if button is None:
        task.log_info('CLOUD_HEAL no verified teleport text; no teleport click sent')
        return False
    task.log_info(f'CLOUD_HEAL verified teleport button={button}')
    task.click_box(button, after_sleep=1)
    if not task.wait_until(task.in_team_and_world, time_out=45, raise_if_not_found=False):
        task.log_info('CLOUD_HEAL teleport did not return to world')
        return False
    task.sleep(2)
    task.log_info('CLOUD_HEAL teleport verified in world')
    return True


def travel_to_heal(task):
    task.executor.interaction.release_all()
    task.next_frame()
    original = candidates(task)
    if not original and close_map_selector(task):
        def fresh_candidates():
            task.next_frame()
            return candidates(task)
        original=task.wait_until(fresh_candidates,time_out=5,raise_if_not_found=False) or []
    if not original:
        original=city_waypoints(task)
    if not original:
        raise RuntimeError('Cloud healing: no waypoint verified in map area')
    if attempt(task, original[0]):
        return
    if os.environ.get('OKWW_HEAL_DEEPSEEK') != '1':
        raise RuntimeError('Cloud healing teleport failed; recovery disabled')
    # Re-read, excluding the failed point. Model selects only among current detections.
    task.next_frame()
    remaining = [b for b in candidates(task)
                 if abs(b.x-original[0].x) >= 15 or abs(b.y-original[0].y) >= 15]
    if not remaining:
        raise RuntimeError('Cloud healing failed: no verified alternative waypoint')
    options = [dict(id=i, x=int(b.x), y=int(b.y), confidence=float(b.confidence)) for i,b in enumerate(remaining)]
    task.log_info('CLOUD_HEAL requesting one bounded deepseek-flash recovery')
    index = choose_recovery(options)
    task.next_frame()
    chosen = remaining[index]
    fresh = next((b for b in candidates(task) if abs(b.x-chosen.x) < 10 and abs(b.y-chosen.y) < 10), None)
    if fresh is None or not attempt(task, fresh):
        raise RuntimeError('Cloud healing recovery failed; stopping')
    task.log_info('CLOUD_HEAL DeepSeek-selected recovery verified locally')
