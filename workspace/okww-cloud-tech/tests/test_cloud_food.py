import tempfile,unittest
from pathlib import Path
from cloud_food import FOOD,FoodReceipt,FoodUnconfirmed,food_duration,selected_food,food_cooldown
from types import SimpleNamespace

class FoodTests(unittest.TestCase):
    def test_cooldown_requires_unique_bounded_seconds(self):
        def boxes(*text):return [SimpleNamespace(name=s) for s in text]
        self.assertEqual(food_cooldown(boxes('59.9s')),59.9)
        for text in [('60分钟',),('拥有10',),('120s',),('0s',),('59s','58s')]:
            self.assertIsNone(food_cooldown(boxes(*text)))
    def test_actual_food_description_and_quantity(self):
        def boxes(*text):return [SimpleNamespace(name=s) for s in text]
        self.assertEqual(selected_food(boxes(FOOD,'拥有11','声骸吸收概率提升50%，持续时间30分','钟，在多人游戏中仅对自己的角色生效。')),(11,1800))
        self.assertIsNone(selected_food(boxes('其他料理','拥有11','持续时间30分钟')))
    def test_duration_requires_one_explicit_supported_value(self):
        self.assertEqual(food_duration('效果持续30分钟'),1800)
        self.assertEqual(food_duration('持续时间：1800秒'),1800)
        self.assertIsNone(food_duration('提高30%'))
        self.assertIsNone(food_duration('持续30分钟，持续60分钟'))
    def test_ambiguous_use_cannot_repeat_or_enable_combat(self):
        with tempfile.TemporaryDirectory() as folder:
            r=FoodReceipt(Path(folder)/'receipt.json','account','session')
            r.begin(FOOD,4,1800,'before.png')
            for count,effect in ((4,False),(2,True),(None,False)):
                with self.assertRaises(FoodUnconfirmed):r.finish(count,effect,'after.png')
            with self.assertRaises(FoodUnconfirmed):r.begin(FOOD,4,1800,'another.png')
            with self.assertRaises(FoodUnconfirmed):r.active()
            r.finish(3,True,'after.png');self.assertTrue(r.active())
            self.assertFalse(FoodReceipt(r.path,'account','different-session').active())
            self.assertTrue(FoodReceipt(r.path,'account','different-session',resume_session='session').active())
            self.assertFalse(FoodReceipt(r.path,'account','different-session',resume_session='unrelated').active())
            self.assertFalse(r.active(now=r.data['uses'][0]['expires_at']))
    def test_either_single_positive_signal_confirms_use(self):
        for after,cooldown in ((3,False),(None,True),(4,True)):
            with self.subTest(after=after,cooldown=cooldown),tempfile.TemporaryDirectory() as folder:
                r=FoodReceipt(Path(folder)/'receipt.json','account','session')
                r.begin(FOOD,4,1800,'before.png');r.finish(after,cooldown,'after.png')
                self.assertTrue(r.active());self.assertIsNone(r.data['pending'])
    def test_wrong_food_or_empty_inventory_not_used(self):
        with tempfile.TemporaryDirectory() as folder:
            r=FoodReceipt(Path(folder)/'receipt.json','account','session')
            for name,n,d in (('other',3,1800),(FOOD,0,1800),(FOOD,3,None)):
                with self.assertRaises(FoodUnconfirmed):r.begin(name,n,d,'before.png')
            self.assertFalse(r.path.exists())

if __name__=='__main__':unittest.main()
