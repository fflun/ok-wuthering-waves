import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cloud_daily_closure import (MAIL_EMPTY, REQUIRED, DailyClosureError, complete,
                                 install, radio_tasks_evidence, radio_rewards_evidence, radio_title,
                                 radio_claim_buttons, earned_reward_popup)
from cloud_daily_closure import radio_cap_cancel, step_complete, TASKS


class DailyClosureTests(unittest.TestCase):
    def test_cap_only_cancels_specific_overflow_popup(self):
        text=SimpleNamespace(name='每周可获经验值即将超出上限，溢出经验无法转换为任何奖励，请确认是否继续领取？',x=313,y=323)
        cancel=SimpleNamespace(name='取消',x=410,y=444)
        confirm=SimpleNamespace(name='确认',x=820,y=444)
        self.assertIs(radio_cap_cancel([text,cancel,confirm]),cancel)
        self.assertIsNone(radio_cap_cancel([text,confirm]))
        text.name='补充结晶波片，是否继续领取？'
        self.assertIsNone(radio_cap_cancel([text,cancel,confirm]))

    def test_cap_skip_requires_cancel_and_all_four_completed_tasks(self):
        p=dict(status='SKIPPED_WEEKLY_CAP',cap_confirmed=True,cancelled=True,experience_claimed=False,
               rows=[dict(task=t,progress=n) for t,n in TASKS])
        self.assertTrue(step_complete('radio_tasks',p))
        self.assertFalse(step_complete('radio_rewards',p))
        for key in ('cap_confirmed','cancelled','experience_claimed','rows'):
            self.assertFalse(step_complete('radio_tasks',{k:v for k,v in p.items() if k!=key}))
        frame,boxes=self.fixture('radio-tasks')
        frame[:]=0
        self.assertEqual(radio_tasks_evidence(frame,boxes,skip_experience=True)['status'],'SKIPPED_WEEKLY_CAP')
        for b in boxes:
            if b.name=='180/180':b.name='120/180'
        with self.assertRaises(DailyClosureError):radio_tasks_evidence(frame,boxes,skip_experience=True)

    def test_short_received_title_requires_centered_title_and_dismiss_prompt(self):
        title=SimpleNamespace(name='获得',x=612,y=172)
        prompt=SimpleNamespace(name='点击空白处继续',x=585,y=629)
        self.assertTrue(earned_reward_popup([title,prompt]))
        self.assertFalse(earned_reward_popup([title]))
        self.assertFalse(earned_reward_popup([prompt]))
        title.x=10
        self.assertFalse(earned_reward_popup([title,prompt]))

    def test_close_variant_requires_both_centered_receipt_and_close_prompt(self):
        title=SimpleNamespace(name='获得',x=612,y=172)
        prompt=SimpleNamespace(name='点击空白区域关闭',x=578,y=629)
        self.assertTrue(earned_reward_popup([title,prompt]))
        self.assertFalse(earned_reward_popup([prompt]))
        for name in ('购买', '等级购买', '解锁寰宇频道', '点击空白区域购买'):
            prompt.name=name
            self.assertFalse(earned_reward_popup([title,prompt]))
        prompt.name='点击空白区域关闭';prompt.y=300
        self.assertFalse(earned_reward_popup([title,prompt]))

    def test_focused_claim_maps_coordinates_and_rejects_purchase(self):
        import numpy as np
        task=Mock();frame=np.zeros((720,1280,3),dtype=np.uint8)
        task.ocr.return_value=[SimpleNamespace(name='一键领取',x=1668,y=1288,width=152,height=40)]
        b=radio_claim_buttons(task,frame)[0]
        self.assertEqual((b.x,b.y,b.width,b.height),(834,644,76,20))
        self.assertEqual(task.ocr.call_args.kwargs['frame'].shape,(1440,2560,3))
        for name in ('解锁寰宇频道','等级购买','键领取'):
            task.ocr.return_value=[SimpleNamespace(name=name)]
            self.assertFalse(radio_claim_buttons(task,frame))

    def test_rewards_only_requires_current_day_verified_prior_steps(self):
        from cloud_autorun_state import day_key
        with tempfile.TemporaryDirectory() as folder:
            task=Mock()
            for prior in (None,dict(game_day='old'),dict(game_day=day_key(),steps={})):
                with self.assertRaises(DailyClosureError):
                    install(task,folder,radio_rewards_only=True,previous_closure=prior)
            prior=dict(game_day=day_key(),steps={k:dict(status='VERIFIED',image='existing') for k in ('mail','radio_tasks')})
            result,_=install(task,folder,radio_rewards_only=True,previous_closure=prior)
            self.assertEqual(result['steps'],prior['steps'])
            self.assertFalse(result['complete'])

    def test_title_crop_excludes_icon_and_requires_exact_known_title(self):
        task=Mock();frame=object()
        task.ocr.return_value=[SimpleNamespace(name='先约电台')]
        self.assertEqual(radio_title(task,frame),'先约电台')
        task.ocr.assert_called_once_with(65/1280,22/720,240/1280,72/720,frame=frame)
        for text in ('0先约电台','等级购买','终端',''):
            task.ocr.return_value=[SimpleNamespace(name=text)]
            self.assertIsNone(radio_title(task,frame))
        task.ocr.return_value=[SimpleNamespace(name=x) for x in ('先约电台','电台任务')]
        self.assertIsNone(radio_title(task,frame))

    def fixture(self, name):
        import cv2
        folder=Path(__file__).resolve().parent/'fixtures/daily_closure'
        frame=cv2.imread(str(folder/(name+'.png')))
        boxes=[SimpleNamespace(name=b['text'],x=b['x'],y=b['y'],width=b['w'],height=b['h'])
               for b in json.loads((folder/(name+'.json')).read_text(encoding='utf-8'))]
        self.assertIsNotNone(frame)
        return frame,boxes
    def test_all_four_real_task_rows_are_claimed(self):
        frame,boxes=self.fixture('radio-tasks')
        self.assertEqual(len(radio_tasks_evidence(frame,boxes)['rows']),4)
        for y in (240,325,409,494):
            changed=frame.copy();changed[y:y+75,1100:1210]=0
            with self.assertRaises(DailyClosureError):radio_tasks_evidence(changed,boxes)
    def test_unfinished_task_cannot_pass_even_with_tick(self):
        frame,boxes=self.fixture('radio-tasks')
        for b in boxes:
            if b.name=='180/180':b.name='120/180'
        with self.assertRaisesRegex(DailyClosureError,'not complete'):radio_tasks_evidence(frame,boxes)
    def test_wrong_page_with_numbers_is_rejected(self):
        frame,boxes=self.fixture('radio-tasks')
        boxes=[b for b in boxes if b.name!='电台任务']
        with self.assertRaisesRegex(DailyClosureError,'page not verified'):radio_tasks_evidence(frame,boxes)
    def test_current_free_reward_requires_tick_and_no_claim_button(self):
        frame,boxes=self.fixture('radio-rewards')
        self.assertEqual(radio_rewards_evidence(frame,boxes)['level'],20)
        with self.assertRaises(DailyClosureError):
            radio_rewards_evidence(frame,boxes+[SimpleNamespace(name='全部领取',x=830,y=645,width=90,height=24)])
        frame[275:345,285:375]=0
        with self.assertRaises(DailyClosureError):radio_rewards_evidence(frame,boxes)
    def test_empty_mail_requires_explicit_message(self):
        self.assertTrue(MAIL_EMPTY.search('全部邮件的附件已经领取完毕'))
        self.assertFalse(MAIL_EMPTY.search('全部领取'))
        self.assertFalse(MAIL_EMPTY.search('没有新邮件'))
    def test_all_parts_and_same_game_day_required(self):
        result=dict(game_day='fixture',complete=True,steps={s:dict(status='VERIFIED') for s in REQUIRED})
        self.assertTrue(complete(result,'fixture'))
        self.assertFalse(complete(result,'other'))
        for s in REQUIRED:
            value=dict(result,steps={k:v for k,v in result['steps'].items() if k!=s})
            self.assertFalse(complete(value,'fixture'))
    def test_native_completion_notification_is_deferred(self):
        with tempfile.TemporaryDirectory() as folder:
            task=Mock();native_log=task.log_info
            install(task,folder)
            task.log_info('Daily Task Completed',notify=True)
            native_log.assert_not_called()
            task.log_info('battle pass')
            native_log.assert_called_once_with('battle pass')
    def test_mail_open_failure_raises_instead_of_skipping(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            task=Mock();task.frame=np.zeros((720,1280,3),dtype=np.uint8)
            task.ocr.return_value=[]
            result,_=install(task,folder)
            with self.assertRaises(DailyClosureError):task.claim_mail()
            self.assertFalse(result['complete'])
            self.assertEqual(result['steps']['mail']['status'],'FAILED')
            task.click.assert_not_called()
    def test_scheduler_rejects_activity_only_success_receipt(self):
        import time
        from cloud_weekly_chain import execute_stage
        from cloud_daily_retry import DailyStageFailure
        from cloud_autorun_state import write_json
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'work/code';root.mkdir(parents=True)
            state=base/'session/background';state.mkdir(parents=True)
            config=dict(python='fixture',browser_deps='fixture',runtime='fixture')
            def child(*args,**kwargs):
                write_json(state/'daily-result.json',dict(status='SUCCEEDED',run_id='owner',completed_at=time.time()+1,
                    daily_verification=dict(complete=True,game_day='fixture',activity=120,verified_rewards=5,verified_at=time.time()+1)))
                return Mock(returncode=0)
            with patch('subprocess.Popen',side_effect=child),patch('cloud_weekly_chain.day_key',return_value='fixture'):
                with self.assertRaisesRegex(DailyStageFailure,'mail/radio'):execute_stage('daily','fixture','owner',0,20,config,root,state)


if __name__=='__main__':unittest.main()
