import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from cloud_autorun_state import day_key,write_json
from cloud_boss_food import prepare_reentry
from cloud_food import FoodReceipt,FoodUnconfirmed,FOOD

class ReentryFoodTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.request=self.root/'request.json'
        self.policy=dict(id='reconnect-test',target='boss',account='a',game_day=day_key(),
                         item=FOOD,quantity=1,status='READY',completed_before=10)
        write_json(self.request,self.policy);self.leave=Mock()
    def call(self,completed=10):
        return prepare_reentry(None,self.root,'synthetic','boss',self.root,self.request,completed,self.leave)
    def consume(self,*args,**kwargs):
        receipt=FoodReceipt(kwargs['receipt_path'],'synthetic',kwargs['session'])
        receipt.begin(FOOD,7,1800,'before');receipt.finish(6,False,'after')
    def test_one_extra_use_and_resume_does_not_repeat(self):
        with patch('cloud_boss_food.prepare',side_effect=self.consume) as action:
            self.assertTrue(self.call());self.assertFalse(self.call(11))
            action.assert_called_once();self.leave.assert_called_once()
        self.assertEqual(json.loads(self.request.read_text())['status'],'DONE')
    def test_pending_blocks_healing_and_eating(self):
        receipt=FoodReceipt(self.root/'boss-food-reentry/reconnect-test.json','synthetic','reentry:reconnect-test')
        receipt.begin(FOOD,7,1800,'before')
        with patch('cloud_boss_food.prepare') as action:
            with self.assertRaises(FoodUnconfirmed):self.call()
            action.assert_not_called();self.leave.assert_not_called()
    def test_completed_receipt_survives_request_update_interruption(self):
        self.consume(receipt_path=self.root/'boss-food-reentry/reconnect-test.json',session='reentry:reconnect-test')
        with patch('cloud_boss_food.prepare') as action:
            self.assertTrue(self.call());action.assert_not_called();self.leave.assert_not_called()
    def test_wrong_progress_or_unsafe_request_id_cannot_consume(self):
        with patch('cloud_boss_food.prepare') as action:
            with self.assertRaises(FoodUnconfirmed):self.call(9)
            self.policy['id']='../bad';write_json(self.request,self.policy)
            with self.assertRaises(FoodUnconfirmed):self.call()
            action.assert_not_called();self.leave.assert_not_called()
    def test_already_world_does_not_navigate_to_healing_point(self):
        from cloud_boss_food import leave_instance_for_food
        task=Mock();task.in_world.return_value=True
        leave_instance_for_food(task)
        task.send_key.assert_not_called();task.revive_at_tower_and_heal.assert_not_called()
        task.reset_to_false.assert_called_once()
    def test_unknown_dungeon_exit_stops_before_click(self):
        from cloud_boss_food import leave_instance_for_food
        task=Mock();task.in_world.return_value=False;task.wait_until.return_value=None
        with self.assertRaises(FoodUnconfirmed):leave_instance_for_food(task)
        task.click_box.assert_not_called();task.reset_to_false.assert_not_called()

if __name__=='__main__':unittest.main()
