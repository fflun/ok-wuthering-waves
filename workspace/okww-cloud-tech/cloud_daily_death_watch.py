"""Return a confirmed domain death to native recovery from a long-action wait."""

def guarded_heavy(char,native,*args,**kwargs):
    task=char.task
    if task.is_browser() and getattr(task,'_in_combat',False):
        from cloud_revive import popup
        task.next_frame()
        if popup(task):
            task.executor.interaction.release_all()
            task.sleep(.25)
            task.next_frame()
            if popup(task):
                # Native confirmation threshold, death exception, domain exit,
                # healing and three-recovery bound remain authoritative.
                task.log_info('CLOUD_DAILY_DEATH confirmed two-frame revive popup during heavy wait')
                task.raise_not_in_combat('Confirmed domain death interrupted long-action wait')
                raise RuntimeError('Native domain death handler unexpectedly returned')
    return native(*args,**kwargs)


def install(material):
    if getattr(material,'_cloud_daily_death_watch',False):return
    native_load=material.load_chars
    def load(*args,**kwargs):
        result=native_load(*args,**kwargs)
        for char in material.chars:
            if char is None or type(char).__name__!='Aemeath' or getattr(char,'_cloud_heavy_death_watch',False):continue
            native=char.heavy_wait_highlight_down
            def heavy(*args,_char=char,_native=native,**kwargs):
                return guarded_heavy(_char,_native,*args,**kwargs)
            char.heavy_wait_highlight_down=heavy
            char._cloud_heavy_death_watch=True
        return result
    material.load_chars=load
    material._cloud_daily_death_watch=True
