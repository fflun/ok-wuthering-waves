"""Select exactly one named book row; validate fresh title/count before travel."""
import re
from cloud_nest_state import TARGET, KEY


def count(text):
    values = re.findall(r'(\d{1,2})\s*/\s*(\d{1,2})', text)
    if len(values) != 1:
        return None
    value = tuple(map(int, values[0]))
    return value if value[1] in (24,36,41,48) and 0 <= value[0] <= value[1] else None


def select(task, allow_unfinished=False, hint=None):
    preferred_key = hint['key'] if hint else KEY
    expected_name = hint['target'] if hint else TARGET
    task.openF2Book('gray_book_boss')
    task.go_nest()
    task.queues = [task.go_nest]
    task._nest_tab_of_current_nest = 'go_nest'
    rows = []
    for box in task.ocr(.35,.13,1,.96,match=task.count_re):
        value = count(box.name)
        if value:
            key = task._make_nest_cache_key(box, str(value[1]))
            if key == preferred_key or (not hint and allow_unfinished and value[0] < value[1]):
                rows.append((box, key, value))
    if allow_unfinished and not hint:
        unfinished = [r for r in rows if r[2][0] < r[2][1]]
        if unfinished:
            rows = sorted(unfinished, key=lambda r: (r[1] != KEY, r[0].y))[:1]
        else:
            rows = [r for r in rows if r[1] == KEY]
    if len(rows) != 1:
        raise RuntimeError('No unique authorized nest row visible')
    box, key, first = rows[0]
    h = task.height_of_screen(1)
    title_rect = (.4, max(0,box.y/h-.075), .72, box.y/h-.018)
    count_rect = (.4, box.y/h-.007, .68, (box.y+box.height)/h+.007)
    def title():
        names = [b.name.replace('像','象').strip() for b in task.ocr(*title_rect)
                 if re.search(r'残[象像]聚落$', b.name.strip())]
        return names[0] if len(names) == 1 else None
    name = title()
    if not name or (key == preferred_key and name != expected_name):
        raise RuntimeError('Selected nest title not positively identified')
    task.next_frame()
    second = count(''.join(b.name for b in task.ocr(*count_rect)))
    if title() != name or second != first:
        raise RuntimeError('Nest title/count changed during verification')
    return box, key, name, first, second
