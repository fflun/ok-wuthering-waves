"""Per-user Windows toast identity; history retention is not proof of reading."""
import base64
import json
import os
from pathlib import Path
import subprocess
import uuid
import xml.etree.ElementTree as ET

APP_ID='OKWW.CloudAutomation'
LABELS={'daily':'每日','boss':'战歌重奏','garden':'幻梦游园',
        'boss_echo':'目标 BOSS 声骸','nest_echo':'残象聚落与声骸'}


def content(task,event):
    stage=LABELS.get(task,'后台任务')
    if event=='RETRYING':return 'OK-WW：'+stage+'失败', '正在自动补做一次，保留已完成进度。'
    if event=='RECOVERED':return 'OK-WW：'+stage+'补做成功', '已完成补做，继续后续任务。'
    if event=='TEST':return 'OK-WW 通知测试', '此消息会保留在通知中心。没有启动游戏。'
    return 'OK-WW：'+stage+'未完成', '已停止；本轮没有剩余自动重试。请查看后台失败通知。'


def install_shortcut(state):
    import pythoncom
    from win32com.shell import shell
    from win32com.propsys import propsys,pscon
    path=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/OKWW 后台任务通知.lnk'
    pythoncom.CoInitialize()
    try:
        link=pythoncom.CoCreateInstance(shell.CLSID_ShellLink,None,pythoncom.CLSCTX_INPROC_SERVER,shell.IID_IShellLink)
        persist=link.QueryInterface(pythoncom.IID_IPersistFile)
        if path.exists():
            persist.Load(str(path))
            if str(link.QueryInterface(propsys.IID_IPropertyStore).GetValue(pscon.PKEY_AppUserModel_ID).GetValue())!=APP_ID:
                raise RuntimeError('Notification shortcut belongs to another application')
            return path
        link.SetPath(str(Path(os.environ['SystemRoot'])/'System32/notepad.exe'))
        link.SetArguments('"'+str(Path(state)/'后台失败通知.txt')+'"')
        link.SetDescription('查看 OK-WW 后台任务失败和补做状态')
        store=link.QueryInterface(propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID,propsys.PROPVARIANTType(APP_ID));store.Commit()
        path.parent.mkdir(parents=True,exist_ok=True);persist.Save(str(path),True)
        return path
    finally:pythoncom.CoUninitialize()


def show_toast_notice(state,task,event):
    install_shortcut(state)
    title,body=content(task,event)
    toast=ET.Element('toast',duration='long')
    binding=ET.SubElement(ET.SubElement(toast,'visual'),'binding',template='ToastGeneric')
    ET.SubElement(binding,'text').text=title;ET.SubElement(binding,'text').text=body
    xml=base64.b64encode(ET.tostring(toast,encoding='utf-8')).decode()
    tag=uuid.uuid4().hex[:16]
    script="""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotifier,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotificationHistory,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.NotificationSetting,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null
$doc=New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('XML')))
$toast=[Windows.UI.Notifications.ToastNotification]::new($doc)
$toast.Tag='TAG';$toast.Group='OKWW'
$toast.ExpirationTime=[DateTimeOffset]::Now.AddDays(3)
$notifier=[Windows.UI.Notifications.ToastNotifier]([Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('APPID'))
$setting='UNAVAILABLE'
if($null -ne $notifier.Setting){$setting=$notifier.Setting.ToString()}
if($setting -notin @('Enabled','UNAVAILABLE')){ throw 'Windows notifications are disabled for this application' }
$notifier.Show($toast)
Start-Sleep -Milliseconds 700
$found=@([Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory('APPID') | Where-Object { $_.Tag -eq 'TAG' }).Count -gt 0
@{app_id='APPID';tag='TAG';setting=$setting;history_retained=$found} | ConvertTo-Json -Compress
""".replace('XML',xml).replace('TAG',tag).replace('APPID',APP_ID)
    shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-WindowStyle','Hidden',
        '-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()],check=True,timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True)
    return json.loads(result.stdout.decode('utf-8-sig').strip())
