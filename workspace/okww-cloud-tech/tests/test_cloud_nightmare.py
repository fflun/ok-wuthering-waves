import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cloud_nightmare_combat import enemies_visible


class NightmareTests(unittest.TestCase):
    def test_requires_both_health_and_objective(self):
        for health, objective in [(False,True),(True,False),(True,True)]:
            task=SimpleNamespace(has_health_bar=lambda:health,ocr=Mock(return_value=[1] if objective else []))
            self.assertEqual(enemies_visible(task),health and objective)
            self.assertEqual(task.ocr.call_count,int(health))
