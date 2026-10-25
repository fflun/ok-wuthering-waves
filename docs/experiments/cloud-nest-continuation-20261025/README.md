# 聚落清怪后有限寻找、未确认吸收则继续（Linux 云游戏实验方案）

这是 fflun 于 **2026-10-25** 修改、部署到自用 Linux 云游戏适配层的源码快照与补丁，沿用仓库根目录的 [AGPL-3.0 许可证](../../../LICENSE.txt)。不改变本分支仓库根目录的 Windows 主程序。

**状态：已部署，离线回归通过；新“未确认吸收继续下一聚落”策略尚未完成游戏内实战验收。此目录不是完整 Linux 移植版、安装包或可直接覆盖上游的 PR。**

## 解决的问题

聚落已清完，但没有找到声骸或没看到吸收成功通知时，旧 Linux 适配层会保留待吸收状态并停止整批任务。新策略在核对已清完的同名聚落之后继续下一个，并明确记录“吸收未确认”。找不到可能是已吸收、没有掉落、识别漏检或位置丢失，不能据此报告吸收成功。

## 搜索与继续规则

1. 清怪后原地检查精确“吸收”提示；识别到提示立即松开移动键，复核后才按 F，并核验吸收通知。
2. 原生前后步行搜索，再使用原图像模型的双帧稳定候选；每次图像寻找最多 **30 秒、30 步**。
3. 原生绕圈 **一次**；必要时回到**同一聚落一次**，再做一次有限寻找。传送加载时间独立于图像寻找时限。
4. 若仍未确认，重新核对同账号、同游戏日、同名聚落以及两次满进度读数，保存带哈希的证据，以 `PICKUP_UNCONFIRMED_ALLOWED` 结束本聚落寻找并继续。
5. 未清怪完成、账号/日期/聚落/计数不一致、停止指令及系统异常，不能当成普通“吸收未确认”处理。

只有本 Linux 完整流程的聚落批次显式开启 `_cloud_nest_continue_unconfirmed=True`；其他调用者保持原严格策略。明确选择较短寻找预算 `_cloud_nest_pickup_seconds=30`，不添加新模型、不降低识别阈值、不无限重试。

## 结果不能混淆

- `verified_pickups`：已核验吸收。
- `pickup_unconfirmed_allowed`：已清怪，有限寻找结束，吸收未确认；`absorbed=false`。
- `searched_no_echo`：严格空搜索证据，不等于已吸收。
- 包含未确认吸收时，整体汇总显示 `SUCCEEDED_WITH_SKIPS`。

已结束的寻找状态按账号、游戏日、聚落保存；重启不会再次强制寻找该聚落。部署不重置日常、周本、战斗检查点或已有领取记录。

## 目录与接入边界

| 文件 | 作用 |
| --- | --- |
| `runtime/cloud_nest_state.py` | 原子保存聚落状态、证据和继续授权；仅依赖标准库 |
| `runtime/cloud_nest_pickup.py` | 有限寻找与通知确认 |
| `runtime/cloud_nest_current.py` | 同账号、同名聚落满进度的接入核验 |
| `runtime/main_cloud_full_echo.py` | 显式开启本次聚落策略的 Linux 子任务适配层 |
| `runtime/cloud_full_chain.py` | 区分吸收成功与未确认的批次回执 |
| `runtime/stage_policy.py` | 阶段继续和带跳过结果汇总；仅依赖标准库 |
| `patches/bounded-nest-continuation.patch` | 相对之前自用 Linux 适配层的六文件差异；不是针对上游 master 的补丁 |
| `tests/test_receipts.py` | 可在干净检出中运行的标准库测试，无游戏输入 |
| `integration/test_continue.py` | 本次 Linux 运行时集成回归源码，需要既有适配层及测试夹具 |

`runtime/` 六份文件依赖未随本方案公开的既有 Linux 适配层（例如 `linux_app`、`main_cloud_daily`、`cloud_revive`、`cloud_nest_entry`、账号/停止控制与框架环境）；不要把六个文件复制进原版后就视为 Linux 版可运行。本次公开的是聚落方案与当前接入源码快照，不包含完整部署环境。

## 如何验证

Python 3.12，在仓库根目录运行（有 `.venv` 时用该环境解释器）：

```sh
python -m unittest discover -s docs/experiments/cloud-nest-continuation-20261025/tests -v
```

这 **7 项**标准库测试覆盖满进度继续、拒绝未完成/错身份数据、证据完整性、重启、未确认吸收与阶段汇总。

集成环境本轮 **102 项**相关测试通过，并通过无游戏输入的完整入口检查。102 包括已有 Linux 适配层回归，不能只凭本目录复现全部测试；集成运行时、既有 `tests.test_cloud_nest_pickup` 夹具和依赖需另备。一个旧测试用 31 秒断言原 90 秒超时，在改动前已失败，本轮由显式 30/90 秒边界测试替代。

## 实战待验收

- 找不到目标时，完成证据保存并进入另一未完成聚落。
- 按 F 后没有成功通知，继续且不报告已吸收。
- 同日重新连接不重打已清完聚落；账号或进度变化仍停止核验。
- 全部聚落扫描结束后，汇总准确列出未确认项，释放输入和进程锁。

不会以一次离线测试代替整套 Linux 版实战通过。

## 上游参考与后续提交

- [NightmareNestTask.py](https://github.com/ok-oldking/ok-wuthering-waves/blob/master/src/task/NightmareNestTask.py)：原生步行、30秒图像搜索和同聚落重传送兜底。
- [BaseCombatTask.py](https://github.com/ok-oldking/ok-wuthering-waves/blob/master/src/task/BaseCombatTask.py)：原生绕圈搜索。
- [贡献要求](https://github.com/ok-oldking/ok-wuthering-waves/blob/master/docs/development/contributing.md)：任务行为大改应先讨论方向。本方案先保存在个人 fork 实验分支；待实战验收和维护者讨论后，再抽取通用改动单独提交，尚未向上游提交本整包 PR。

代码审阅：Codex 对本次六文件改动、证据核验、默认严格模式、继续条件与汇总进行审阅；未声称独立审查服务或维护者已接受。

仅发布代码、合成测试与说明；没有发布真实截图、运行日志、账号标识、密码、密钥、登录会话、个人配置、状态账本或管理连接资料。
