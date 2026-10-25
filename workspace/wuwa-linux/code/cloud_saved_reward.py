"""Resume a positively verified, already completed daily Tacet before healing."""
import re,time
def resume_completed_reward(active,pending_path):
 from src.task.TacetTask import TacetTask
 from cloud_daily_policy import PendingClaim,claim,verified_inventory
 from cloud_material_combat import observe,require_completion
 material=active.get_task_by_class(TacetTask)
 material._cloud_daily_no_refill=True
 from cloud_victory_checkpoint import for_task
 checkpoint=for_task(material)
 saved=checkpoint.assert_resume() if checkpoint else None
 material.next_frame()
 # A claim dialog is positive saved progress too; an uncertain spending journal
 # is always a hard stop before this function is called.
 journal=PendingClaim(pending_path);journal.assert_clear()
 dialog=material.has_claim_stamina()
 if not dialog:
  if not material.in_realm():
   if saved:raise RuntimeError('Saved victory scene missing; no new entry, battle, or generic exit allowed')
   return False
  status=observe(material,fresh=True)
  if saved and status not in ('PENDING','COMPLETE'):
   raise RuntimeError('Saved victory is not a positive reward scene; no combat or exit allowed')
  if status=='ACTIVE':
   # Reconnecting the cloud client may resume the same timed challenge.
   # Continue native combat instead of exiting or starting another one.
   confirmed=0
   for _ in range(12):
    material.next_frame()
    objective=''.join(b.name for b in material.ocr(.005,.20,.34,.32))
    identified=bool(re.search(r'清理[无無]音[区區].*残象|清理[无無]音[区區].*殘象',objective))
    confirmed=confirmed+1 if identified else 0
    if confirmed>=2:break
    material.sleep(.2)
   else:raise RuntimeError('Saved active realm is not positively identified as Tacet after fresh observations; no entry or combat')
   material.load_chars()
   chars=[type(c).__name__ for c in material.chars if c]
   if len(chars)!=3 or 'BaseChar' in chars:raise RuntimeError('Saved challenge team not recognized; no combat or spending')
   material.log_info('CLOUD_SAVED_ACTIVE resume existing challenge with native combat; no new entry')
   material.combat_once(target=True)
   status='COMPLETE'
  if status not in ('PENDING','COMPLETE'):return False
  require_completion(material,'resume_saved_reward')
  material.load_chars()
  material.walk_to_treasure()
  material.pick_f(handle_claim=False)
  material.wait_until(material.has_claim_stamina,time_out=5,raise_if_not_found=True)
 current,reserve=verified_inventory(material)
 if current<120:raise RuntimeError('Saved reward requires reconciliation: not enough natural waveplates for native double claim; no refill authorized')
 material.log_info('CLOUD_SAVED_REWARD resume existing completed Tacet; no new battle')
 _,cost=claim(material,journal,once=60,must_use=180,multiplier=2)
 material.log_info(f'CLOUD_SAVED_REWARD_VERIFIED cost={cost} before={current} reserve={reserve}')
 material.next_frame()
 buttons=material.ocr(.25,.77,.48,.91,match=re.compile(r'^退出副本$'))
 if len(buttons)!=1:raise RuntimeError('Saved reward claimed; result exit not positively identified, do not replay claim')
 material.click_box(buttons[0],after_sleep=1)
 material.wait_in_team_and_world(time_out=120)
 return True
