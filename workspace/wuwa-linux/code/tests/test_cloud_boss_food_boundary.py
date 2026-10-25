import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from cloud_boss_food import prepare_transition,transition_receipt
from cloud_food import FoodReceipt,FOOD,FoodUnconfirmed

class BoundaryFoodTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.old=FoodReceipt(transition_receipt(self.root,'account','old'),'account','old')
        self.old.begin(FOOD,5,1800,'before');self.old.finish(4,False,'after')
        self.used=self.old.data['uses'][0]['used_at']
    def consume(self,*args,**kwargs):
        r=FoodReceipt(kwargs['receipt_path'],'account',kwargs['session'])
        r.begin(FOOD,4,1800,'before');r.finish(3,False,'after')
    def call(self,**kwargs):
        return prepare_transition(None,self.root,'account','next',self.root,**kwargs)
    def test_before25_minutes_no_food_and_resume_never_renews(self):
        with patch('cloud_boss_food.time.time',return_value=self.used+1499),patch('cloud_boss_food.prepare') as eat:
            self.call();eat.assert_not_called()
        with patch('cloud_boss_food.time.time',return_value=self.used+2000),patch('cloud_boss_food.prepare') as eat:
            self.call();eat.assert_not_called()
    def test_at25_minutes_one_use_and_resume_no_repeat(self):
        with patch('cloud_boss_food.time.time',return_value=self.used+1500),patch('cloud_boss_food.prepare',side_effect=self.consume) as eat:
            self.call();self.call();eat.assert_called_once()
    def test_mid_batch_without_receipt_cannot_eat_after_expiry(self):
        with patch('cloud_boss_food.time.time',return_value=self.used+2000),patch('cloud_boss_food.prepare') as eat:
            self.call(completed=1);eat.assert_not_called()
    def test_other_account_cannot_supply_active_effect(self):
        with patch('cloud_boss_food.prepare') as eat:
            def consume_other(*a,**k):
                r=FoodReceipt(k['receipt_path'],'other',k['session'])
                r.begin(FOOD,4,1800,'before');r.finish(3,False,'after')
            eat.side_effect=consume_other
            prepare_transition(None,self.root,'other','next',self.root)
            eat.assert_called_once()
    def test_same_account_pending_prevents_new_use(self):
        self.old.begin(FOOD,4,1800,'uncertain')
        with patch('cloud_boss_food.prepare') as eat:
            with self.assertRaises(FoodUnconfirmed):self.call()
            eat.assert_not_called()
    def test_reentry_use_counts_toward25_minute_threshold(self):
        r=FoodReceipt(self.root/'boss-food-reentry/reconnect.json','account','reentry')
        r.begin(FOOD,4,1800,'before');r.finish(3,False,'after')
        with patch('cloud_boss_food.time.time',return_value=r.data['uses'][0]['used_at']+100),patch('cloud_boss_food.prepare') as eat:
            self.call();eat.assert_not_called()

if __name__=='__main__':unittest.main()
