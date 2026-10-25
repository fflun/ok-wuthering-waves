"""Platform process ownership; stop the owned group, never unrelated browsers."""
import os,signal,subprocess

def spawn_options():
    if os.name=='nt':
        return {'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {'start_new_session':True}

def terminate_tree(child):
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return
    try: os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError: return
    try: child.wait(timeout=8)
    except subprocess.TimeoutExpired: pass
    try: os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    child.wait(timeout=5)
