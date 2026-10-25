"""Failure-only SMTP notices. Credentials come from the process environment."""
import json
import os
import smtplib
import ssl
import base64
import subprocess
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime
from cloud_autorun_state import write_json, day_key


def notification_ready(cfg):
    local = cfg.get('local_enabled') is True and os.name == 'nt'
    mail = (cfg.get('enabled') is True and cfg.get('host') and cfg.get('sender')
            and cfg.get('recipients') and cfg.get('security') in ('ssl', 'starttls')
            and os.environ.get(cfg.get('username_env', ''))
            and os.environ.get(cfg.get('password_env', '')))
    return bool(local or mail)


def show_local_notice(test=False):
    # Notification area only: no window activation or modal dialog.
    title = 'OK-WW 本机通知测试' if test else 'OK-WW 后台任务已停止'
    body = ('这是一条通知测试，没有启动游戏。' if test else
            '任务未完成，已停止。请查看 OKWW-后台每日 的运行状态及后台失败通知。')
    script = """
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notice=New-Object System.Windows.Forms.NotifyIcon
try {
 $notice.Icon=[System.Drawing.SystemIcons]::Information
 $notice.Text='OK-WW'
 $notice.Visible=$true
 $notice.ShowBalloonTip(8000,'TITLE','BODY',[System.Windows.Forms.ToolTipIcon]::Info)
 $until=[DateTime]::UtcNow.AddSeconds(9)
 while([DateTime]::UtcNow -lt $until) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 100 }
} finally { $notice.Dispose() }
""".replace('TITLE', title).replace('BODY', body)
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                    '-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode()],
                   check=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def notify_failure(state, task, reason,event='FAILED'):
    state=Path(state)
    record={'task':task,'day':day_key(),'reason':reason,
            'at':datetime.now().astimezone().isoformat(),'status':'PENDING','event':event}
    if event in ('RETRYING','RECOVERED'):
        # Keep the retry audit, without replacing the terminal failure notice
        # or dispatching a toast/mail while the flow can continue.
        record.update(status='SUPPRESSED_POLICY',local_status='DISABLED',mail_status='DISABLED')
        with (state/'notice-history.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        return
    from cloud_toast_notice import content
    title,body=content(task,event)
    (state/'后台失败通知.txt').write_text(title+'\n'+body+'\n时间：'+record['at']+'\n',encoding='utf-8')
    # Always retain a local notice even if SMTP is unavailable.
    write_json(state/'failure-notice.json',record)
    try:
        cfg=json.loads((state/'notifications.json').read_text(encoding='utf-8'))
        record['local_status']='DISABLED'
        if cfg.get('local_enabled'):
            try:
                if cfg.get('toast_enabled'):
                    from cloud_toast_notice import show_toast_notice
                    result=show_toast_notice(state,task,event)
                    record['toast']=result
                    if not result.get('history_retained'):raise RuntimeError('Notification was not retained')
                else:show_local_notice()
                record['local_status']='DISPATCHED'
            except Exception as exc:
                record['local_status']='SEND_FAILED'
                record['local_error_type']=type(exc).__name__
        if not cfg.get('enabled'):
            record['mail_status']='DISABLED'
            record['status']='LOCAL_DISPATCHED' if record['local_status']=='DISPATCHED' else 'NOT_DELIVERED'
            return
        if cfg.get('security') not in ('ssl','starttls'):
            raise ValueError('TLS required')
        recipients=cfg.get('recipients',[])
        if not recipients or not all(isinstance(x,str) and '@' in x for x in recipients):
            raise ValueError('Recipient required')
        message=EmailMessage()
        message['From']=cfg['sender']
        message['To']=', '.join(recipients)
        message['Subject']=title+'（'+record['day']+'）'
        # Do not mail raw logs, screenshots, account data or exception strings.
        message.set_content(title+'\n'+body+'\n'
                            '请在电脑上查看 OKWW-后台每日 的运行状态和日志。\n'
                            f'时间：{record["at"]}\n')
        username=os.environ[cfg['username_env']]
        password=os.environ[cfg['password_env']]
        context=ssl.create_default_context()
        if cfg['security']=='ssl':
            server=smtplib.SMTP_SSL(cfg['host'],int(cfg.get('port',465)),timeout=15,context=context)
        else:
            server=smtplib.SMTP(cfg['host'],int(cfg.get('port',587)),timeout=15)
        with server:
            if cfg['security']=='starttls':
                server.ehlo();server.starttls(context=context);server.ehlo()
            server.login(username,password)
            server.send_message(message,to_addrs=recipients)
        record['status']='SENT'
        record['mail_status']='SENT'
    except Exception as exc:
        record['status']='SEND_FAILED'
        record['error_type']=type(exc).__name__
    finally:
        write_json(state/'failure-notice.json',record)
        with (state/'notice-history.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')


def notify_retry(state,task,reason):
    return notify_failure(state,task,reason,event='RETRYING')


def notify_recovered(state,task):
    return notify_failure(state,task,'retry completed',event='RECOVERED')
