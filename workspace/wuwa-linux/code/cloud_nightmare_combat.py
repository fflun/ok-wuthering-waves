"""Positive enemy evidence for cloud nests when the lock marker is unreadable."""
import re


def enemies_visible(task):
    if not task.has_health_bar():
        return False
    objective = task.ocr(.005, .18, .28, .43,
                         match=re.compile('清剿残[象像]聚落|梦魇拔除|夢魘拔除'))
    # Close enemies can have their level clipped above the viewport. The native
    # red enemy-health detector plus the live nest objective is sufficient.
    return bool(objective)
