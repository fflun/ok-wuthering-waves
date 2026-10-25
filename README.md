# 云鸣潮 Windows 源码版（2026-10-25）

本分支是本机正在使用的Windows版本源码快照，包含浏览器传输、日常/每周流程、原生战斗与角色代码、资源与领奖核验、多账号隔离、后台运行和进程控制，以及固定的`ok`框架源码和识别资产。不是上游原版的简单链接，也没有将Linux新补丁覆盖到本机版本。

- [Linux服务器版本](https://github.com/fflun/ok-wuthering-waves/tree/platform/linux-cloud-20261025)
- [验证范围与隐私边界](PUBLICATION.md)
- [许可证及第三方来源](THIRD_PARTY_CLOUD.md)

## 目录

`workspace/okww-cloud-tech`是本机应用与适配源码；`workspace/okww-cloud-runtime-v367`保存该版本使用的框架Python源码和资产。运行后生成的`workspace/okww-cloud-session`是私有目录，未提交。

## 准备与检查

使用Python 3.12、Windows、Chrome。先创建独立环境，不复用当前生产运行目录：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe verify_source.py
.\run-windows.ps1 -Mode help
```

`run-windows.ps1`显式设置源码和固定框架路径。默认只显示帮助，不启动游戏。

## 登录与实际任务

```powershell
.\run-windows.ps1 -Mode login
# 在官方页面完成自己的登录；登录状态只保存在本机私有会话目录。
.\run-windows.ps1 -Mode daily
```

先自行完成账号配置、身份绑定、任务目标和资源策略核对。需要注册A/B/C隔离目录时，`cloud_accounts.write_initial_configuration`提供空模板；不会随公开包提供任何已绑定的账号、验收标记或可用登录态。按需任务参数查看`main_cloud_daily.py --help`。不要同时在另一台机器运行同一账号。

原`Install-CloudAutoDaily.ps1`、`register_cloud_logon.ps1`与`main_cloud_autodaily.py`保留在源码目录；发布不会执行它们。启用调度前应在自己的环境完成日常、通知、锁与重启恢复验收，不能复制旧环境的验收凭证。

## 已知范围

本机已有实际日常、周任务与若干聚落验证；各功能的旧验收不等于任意账号、画质和线路都可直接通用。最新Linux专用“清怪后吸收未确认则继续”在Linux分支，未擅自合并到这一Windows快照。详细说明见PUBLICATION.md。

根目录原版src/assets等保留作为上游基线；本分支的云版本请使用上述workspace入口。源码快照不附带打包exe。
