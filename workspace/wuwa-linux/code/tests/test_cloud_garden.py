import unittest
from cloud_garden_guard import parse_progress,page_value,positioned_page_value,result_progress
from types import SimpleNamespace

class GardenProgressTests(unittest.TestCase):
    def cap_screen(self):
        return [SimpleNamespace(name=name,x=x,y=y) for name,x,y in
                [('挑战成功',719,146),('本周游历值',509,373),
                 ('已达到上限',936,373),('返回主页',805,597),
                 ('通关阶段12，可获得6000游历值',512,449)]]

    def test_actual_cap_screen_requires_no_old_template(self):
        self.assertEqual(result_progress(self.cap_screen()),(6000,6000))

    def test_unrelated_cap_text_and_conflicting_ratio_are_rejected(self):
        for changed in ('row','title','return','ratio'):
            boxes=self.cap_screen()
            if changed=='row':boxes[2].y=310
            elif changed=='title':boxes=boxes[1:]
            elif changed=='return':boxes=boxes[:3]+boxes[4:]
            else:boxes.append(SimpleNamespace(name='3600/6000',x=922,y=404))
            with self.assertRaises(RuntimeError):result_progress(boxes)

    def test_full_page_positions_exclude_other_6000_values(self):
        boxes=[SimpleNamespace(name='周度游历',x=388,y=81),
               SimpleNamespace(name='0',x=248,y=605),
               SimpleNamespace(name='6000',x=779,y=484)]
        boxes += [SimpleNamespace(name=str(value),x=x,y=644)
                  for value,x in zip(range(1000,6001,1000),(401,541,683,825,968,1107))]
        self.assertEqual(positioned_page_value(boxes),(0,6000))
        with self.assertRaises(RuntimeError):positioned_page_value(boxes[:-1])

    def test_actual_page_has_standalone_current_and_six_milestones(self):
        self.assertEqual(page_value(['0','游历值'],['1000','2000','3000','4000','5000','6000']),(0,6000))
        self.assertEqual(page_value(['6000','游历值'],['1000','2000','3000','4000','5000','6000']),(6000,6000))

    def test_page_missing_current_or_milestone_is_not_complete(self):
        for current,markers in (([],['1000','2000','3000','4000','5000','6000']),
                                (['6000'],['1000','2000','3000','4000','5000'])):
            with self.assertRaises(RuntimeError):page_value(current,markers)

    def test_partial_and_complete_are_distinct(self):
        self.assertEqual(parse_progress(['1200/6000']),(1200,6000))
        self.assertEqual(parse_progress(['6000/6000']),(6000,6000))
        self.assertEqual(parse_progress(['0/6000']),(0,6000))

    def test_empty_or_target_only_does_not_mean_complete(self):
        for texts in ([],['6000'],['领取奖励'],['6000/6000','1200/6000'],['7000/6000']):
            with self.assertRaises(RuntimeError):parse_progress(texts)

    def test_punctuation_is_allowed_without_changing_numbers(self):
        self.assertEqual(parse_progress(['当前游历值 1,200 ／ 6,000']),(1200,6000))

if __name__=='__main__':unittest.main()
