import ast,re,sys,unittest
from pathlib import Path
from types import SimpleNamespace,ModuleType
from unittest.mock import Mock,patch
from cloud_all_boss import named_active_battle,protect_named_instance,retain_named_instance,positive_victory

class NamedHPTests(unittest.TestCase):
    target={'name':'海之女','aliases':['海之女·荣光的灰烬']}
    def task(self,title='Lv.85 海之女·荣光的灰烬',hp=True,count=3,popup=False,objective=''):
        task=SimpleNamespace(next_frame=Mock(),in_team=lambda:(True,0,count),
            check_health_bar=lambda:hp,log_info=Mock())
        task.ocr=lambda *area,**kwargs: ([SimpleNamespace(name='选择复苏物品')] if popup else []) if kwargs else [SimpleNamespace(name=title if area[1]==0 else objective)]
        return task

    def test_live_named_hp_without_objective_keeps_battle(self):
        task=self.task();self.assertTrue(protect_named_instance(task,self.target))
        self.assertTrue(task._cloud_weekly_trial);task.next_frame.assert_called_once()

    def test_named_hp_resume_retains_original_scene_without_map(self):
        task=self.task();native=Mock()
        retain_named_instance(task,self.target,native)
        native.assert_not_called()

    def test_wrong_name_missing_hp_incomplete_team_and_revive_are_rejected(self):
        for kwargs in ({'title':'其他Boss'},{'hp':False},{'count':2},{'popup':True}):
            with self.subTest(kwargs=kwargs):
                task=self.task(**kwargs);self.assertFalse(named_active_battle(task,self.target))
                self.assertFalse(hasattr(task,'_cloud_weekly_trial'))

    def test_old_reward_name_without_hp_does_not_authorize_combat(self):
        self.assertFalse(named_active_battle(self.task(hp=False,objective='领取奖励'),self.target))

    def test_fresh_frame_replaces_stale_name_and_hp(self):
        task=self.task()
        task.next_frame=lambda:setattr(task,'check_health_bar',lambda:False)
        self.assertFalse(named_active_battle(task,self.target))

    def test_hp_is_enemy_evidence_and_never_victory(self):
        self.assertFalse(positive_victory(seen=True,team=True,enemies=True,active=False,recovery=False,reward=True))

    def test_real_recovery_callback_enables_protection_after_initial_missing_hp(self):
        source=Path(__file__).resolve().parents[1]/'cloud_all_boss.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='recovery']
        self.assertEqual(len(calls),1)
        callback=next(k.value for k in calls[0].keywords if k.arg=='active_check')
        task=self.task(hp=False);task._cloud_weekly_trial=False
        self.assertFalse(protect_named_instance(task,self.target))
        task.check_health_bar=lambda:True
        fn=eval(compile(ast.Expression(callback),str(source),'eval'),{'protect_named_instance':protect_named_instance,'task':task,'target':self.target})
        self.assertTrue(fn());self.assertTrue(task._cloud_weekly_trial)

    def test_original_domain_guard_accepts_hp_only_with_scoped_protection(self):
        source=Path(__file__).resolve().parents[1]/'src/combat/CombatCheck.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CombatCheck')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='cloud_domain_still_active')
        namespace={'re':re};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(source),'exec'),namespace)
        modules={}
        for name in ['DomainTask','TacetTask','NightmareNestTask']:
            mod=ModuleType('src.task.'+name);setattr(mod,name,type(name,(),{}));modules[mod.__name__]=mod
        task=self.task();task.is_browser=lambda:True
        protect_named_instance(task,self.target)
        with patch.dict(sys.modules,modules):
            self.assertTrue(namespace['cloud_domain_still_active'](task))
            task._cloud_weekly_trial=False
            self.assertFalse(namespace['cloud_domain_still_active'](task))

if __name__=='__main__':unittest.main()
