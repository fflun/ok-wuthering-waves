# 云鸣潮 Linux 服务器源码版（2026-10-25）

这是服务器当前运行的Linux源码快照，包含全部应用/角色/任务源码、Linux浏览器设备层、CPU OCR/声骸识别、固定框架Python源码及识别资产，以及当前使用的会话所有权和完整流程调度代码。

- [本机Windows版本](https://github.com/fflun/ok-wuthering-waves/tree/platform/windows-cloud-20261025)
- [验证范围、私有状态与许可说明](PUBLICATION.md)
- [第三方来源](THIRD_PARTY_CLOUD.md)

## 目录与部署布局

| 源码目录 | 作用 |
| --- | --- |
| `workspace/wuwa-linux/code` | 服务器当前应用、适配、任务及测试源码 |
| `workspace/wuwa-linux/vendor/ok` | 服务器使用的固定框架Python源码，已包含Linux兼容修改 |
| `workspace/wuwa-linux/assets` | 固定识别资产与声骸模型 |
| `workspace/full-alignment-20261023` | 同会话完整流程、锁/停止控制、会话生命周期与阶段汇总 |
| `framework-linux.patch` | 框架Linux兼容修改的原始差异参考 |

## 环境与无输入检查

Python **3.12**；Ubuntu/Debian、Chromium及其系统库、中文字体和Xvfb显示服务。Python依赖与服务器当前CPU环境一致，不安装Windows输入组件或OpenVINO/NPU。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python verify_source.py
DISPLAY=:99 bash run-linux.sh preflight
bash run-linux.sh help
```

`preflight`只构造任务、验证进程锁和清理；不登录、不启动游戏任务。Xvfb需先由部署者准备。真实浏览器路径通过`OKWW_CHROMIUM`设置，必须是已安装的实际Chromium二进制；不随源码发布浏览器安装包。

## 实际运行前配置

完整服务器调度源码保留原部署布局约定：应用位于`/opt/cloudgames/wuwa-20261023`、完整调度位于`/opt/cloudgames/full-alignment-20261023`。迁到新机时，可将上述workspace两个源码目录分别部署到对应位置，或先一致地调整这些路径。不要覆盖已有生产目录、锁或会话。

使用独立非root运行用户，准备共享锁目录、显示服务与运行目录权限；设置`OKWW_INSTALLED_RUNTIME`及`PYTHONPATH`指向该应用/框架。`main_cloud_background.py login`提供官方登录页面；实际日常入口参数见`main_cloud_daily.py --help`。完整调度入口是`run_aligned_full.py --scheduled`，包含自己的锁、账号、停止、资源待确认事务与每周证据核对，不能在已有运行者旁另起实例。

账号注册/绑定、任务目标、每周参考身份、通知及私人浏览器会话需在新机配置。源码没有复制这些凭据和验收材料；未配置时安全拒绝是预期行为，不能通过关闭核验或伪造完成记录来启动。Python依赖和完整源码已提供，但本快照不是自动初始化账号的安装器。

## 当前功能与验证

- 日常、三次周本与周常优先，可选Boss/聚落声骸失败后进入下一阶段；成功领取与次数按真实回执记账。
- 每周已完成记录按游戏周复用，避免重刷。
- 保留当前资源、领取、复苏和账号核验，不在发布时改变额度或清除记录。
- 最新聚落规则：清怪完成后有限步行、图像、绕圈和同聚落重定位寻找；仍未确认吸收时保存证据继续下一聚落，结果单独列为未确认。不是吸收成功证明。
- 当前日常已有实际自动运行成功；本次聚落策略102项相关离线测试及无输入入口检查通过，新策略仍待下一次真实聚落运行验收。此前可选声骸阶段的失败不能写成整套全部成功。

原`code/linux/README.md`说明的是早期离线设备层，现仅保留为历史设计参考；当前部署与入口以本README和完整调度代码为准。

根目录上游原版src/assets等保留为基线；Linux云版本使用workspace目录。没有复制或更改本机Windows登录态与配置。
