# Linux 浏览器设备与离线识别验证

最新状态：香港 **stage2 的离线浏览器设备初始化、原版执行器取帧、CPU OCR 和模板识别已验证**。真实云游戏模式仍未启用，没有连接已有登录窗口，没有启动游戏任务。此前 stage1 仅做模块导入，已保留，可独立回查。

## 独立环境

- 当前目录：`/home/pinwheeladmin/okww-linux-offline/20261004-stage2`。
- 独立 `.venv` 和 `vendor/ok` 源码快照；原安装版、`/opt/pinwheel-wuwa`、桌面、代理、小三月均未改动。
- 实际依赖固定在 `requirements-stage2.lock.txt`；使用 onnxocr-ppocrv5 0.0.22、ONNX Runtime 1.30.0、Playwright 1.63.0、OpenCV headless 4.14.0.94。
- OCR 模型由包自带；CPU 模式关闭 OpenVINO/NPU，不下载游戏数据。中文测试字体来自 Debian 的 fonts-wqy-zenhei 软件包，解包到本 stage，不安装至系统；许可证一并保留。
- `recognition-provenance.json` 记录模型/缓存和字体包 SHA256；源文件及框架补丁另有前后散列清单。
- 磁盘约 566 MiB；没有新增服务、定时任务或常驻进程。

OCR 后端选择依据：[onnxocr-ppocrv5 0.0.22 官方包说明](https://pypi.org/project/onnxocr-ppocrv5/0.0.22/)，包支持 CPU ONNX Runtime 并自带 PP-OCRv5 模型。模型声明能力不能代替本环境测试。

## 启动路径

`main_cloud_linux.py` 默认只打印离线状态；显式 `--probe` 才进入本阶段验证：

1. LinuxBrowserDeviceManager 启动独立、无登录资料的无界面 Chromium。
2. 只允许 about:blank，浏览器上下文离线、拦截页面网络请求，禁止服务工作线程；不支持游戏 URL。
3. Chromium 只显示脚本生成的中文文字和模板图块；沿用连接器的 surfaceMetrics 函数读取 canvas PNG，没有网页截图回退。
4. 构造真实原版 TaskExecutor、GlobalConfig、FeatureSet；不创建任何游戏任务，不启动任务队列。
5. 原版 executor.next_frame 取到 1280×720 画面，逐像素与源图相等。交互层及设备后端都拒绝输入，即便误改 block_input 标志也无法发送。
6. 用原版 TaskExecutor.ocr_lib 创建 CPU OCR；用原版 FeatureSet.find_one_feature 做模板正负样本测试。
7. 最后清理浏览器、Playwright 子进程和事件循环；两次验证均无剩余子进程。

框架独立副本保留按需加载后端、纯 geometry 函数提取；本阶段再为 prevent_sleeping 增加非 Windows 分支。没有改角色轮转、每日调度、复活恢复和战斗主循环。

## 实测资源（1 vCPU，1280×720 合成画面）

测试进程限制为一个可用 vCPU、低优先级运行，避免占满这台 2 核机器。进程树含 Python、Playwright 与其新开的 Chromium；不包含原服务。

| 项目 | 初次 / 复测 |
|---|---|
| 浏览器与设备初始化 | 11.686 秒 / 2.804 秒 |
| OCR 模型加载 | 0.925 秒 / 0.363 秒 |
| 整幅中文 OCR，3 次均值 | 1226.68 ms / 1049.75 ms |
| 文字区域 OCR，3 次均值 | 543.81 ms / 541.68 ms |
| 整幅模板匹配，10 次均值 | 190.71 ms / 180.74 ms |
| 局部模板匹配，10 次均值 | 复测 1.24 ms，最大 4.79 ms |
| 合计峰值 PSS | 927.74 MiB / 850.17 MiB |
| 合计峰值 RSS | 1483.41 MiB / 1409.34 MiB |

PSS 按比例分摊进程共享内存，适合看这组进程的大致合计占用；直接相加 RSS 会重复计入部分共享内存。峰值以 100 ms 间隔采样，可能漏掉更短的瞬时峰值。第二次存在 OS/模型缓存，不能当成全新环境冷启动结果。

识别结果：中文“领取奖励”“双倍领取”“兑换次数：2”和“结晶波片120/240”均被识别。整幅图额外把随机模板噪声识别为一个短横线，已保留原输出；文字区域无此额外结果，纯白负样本无文本。模板目标位置正确，纯白负样本未命中。

Windows / Linux 各 38 项离线回归通过；Linux 实际任务类/战斗恢复契约检查通过；pip check 通过。已有五项服务的状态、主进程号和启动时间前后相同。

## 复测

运行：`sh /home/pinwheeladmin/okww-linux-offline/20261004-stage2/code/linux/check-runtime.sh`。

只进行上述离线测试，正常结束自动清理进程，Ctrl+C 可中止。原始结果写入本 stage 的 probe-state/runtime-result.json；调用时不需要登录或进入游戏。不要在这里运行 Windows 的 main_cloud_daily.py --connect。

本地证据：`../../../outputs/linux-runtime-20261004/evidence/`。stage1 原始证据保留于 `../../../outputs/linux-offline-20261004/evidence/`。源码包不包含浏览器配置、凭据或游戏截图。

## 尚未验收

- 真实视频流、requestVideoFrameCallback 连续新帧、页面重连、队伍识别、真实游戏模板和压缩画面的 OCR 准确率。
- 真实浏览器键鼠输入、时延、实战与无人值守每日。当前 Linux 入口刻意不提供游戏模式。
- 这次仅用合成模板，不是完整游戏资产库的加载/识别验收；静态图耗时不能推断实时战斗帧率。

后续可先用本地动态视频样本检查新帧/失帧恢复，仍不进入游戏；真实游戏模式需在用户要求继续实测时单独开放。
