# 验证记录

日期：2026-10-08。交付状态：扩展已实现并通过软件流程测试；真实模型推理和真实病例准确度尚未验收。

## 实测运行环境

- Windows，本工作区独立安装的 Slicer 5.12.4。
- 官方 Windows 安装文件 SHA-512 与下载页一致：`5ba320cb67f0acdaacf0a31380e9cf3b9f46d05f57a53da7e04ebcd9490251ecbe998bfefdbdab1f747e038653177868cdb0ad30986473b9d68efba0f4c6045c`。
- 上游 SlicerTotalSegmentator 固定提交：`270cac20b78a282505e4f6a25d268666e4056019`。
- TotalSegmentator 2.14.0、PyTorch 2.14.1+cpu、nnunetv2 2.8.1、NumPy 2.4.6。`pip check` 输出 No broken requirements found。
- 独立测试运行时 Python 3.12.14、NumPy 2.3.5。
- PyTorch 实测 `CUDA available: False`，本次只验证 CPU 进程接口；未验证 GPU 路径。
- 全部安装包及依赖在本工作区 tools 中，未修改其他 Slicer 安装。

## 已执行且通过

独立测试 `python -m unittest discover -s tests -v`：15 项，覆盖斜切物理投影、左右方向、无效几何、内部锚点、标签避让、体素体积、研究包校验/路径/事务失败和 worker 失败记录。

真实 Slicer 测试 `scripts/test-slicer.ps1`：合成 CT 集成流程通过，包含：

- CT 体积与合成分割导入。
- 人工编辑副本不改变自动基准；脚本篡改自动基准可检测。
- 单纯保存或保存失败不改变“已开始修正”状态。
- 已运行模型的缺失结构产生零体积 / absent 记录。
- 病例包排除其他病例节点。
- NIfTI 导出、几何与像素读回校验。
- 场景关闭并重开后的影像、自动/修正结果及模型记录一致。
- 无有效图谱节点的研究包被拒绝，并回滚原场景。
- 模块加载、中文结构名称、轴位引线标签显示。
- Segment Editor 掩膜变化使标签缓存失效。
- 真正启动 PythonSlicer 子进程，默认禁止下载时缺权重明确失败，不导入伪结果。
- 场景关闭终止运行中的子进程，丢弃陈旧结果。

测试中定位并修复了 PythonQt QByteArray 日志转换差异；旧失败日志不作为最终通过依据。最终结果与截图位于忽略目录 test-results。

## 尚未通过的验证

尝试对合成头部运行真实 `head_glands_cavities` 模型并下载权重。官方 GitHub 权重文件约 231 MB，下载持续仅几十 KB/s；运行八分钟后完成约 5%，于是主动停止本测试。退出码 -1，为中断而非成功；未完成真实推理，不报告任何模型精度或速度数字。

这不影响界面、研究包和缺权重错误流程的测试结果，但完整自动分割成功路径（模型输出 → 上游 importer → 本扩展）仍需权重准备后执行。两项任务都还需 Dataset298 裁剪模型。推理 worker 已将目标及裁剪模型权重一起纳入检查和运行哈希记录。

也尚未取得用户真实病例。3–5 个脱敏头颈 CT、人工核对边界与方向、病例级时间和硬件资源记录仍是研究使用前的验收事项。不能把合成测试当作模型准确度验证。

## 继续真实模型测试

```powershell
.\tools\Slicer\bin\PythonSlicer.exe .\tests\model_smoke.py head_glands_cavities
# 第一项成功后，再运行第二项；不用于评估医学准确度。
.\tools\Slicer\bin\PythonSlicer.exe .\tests\model_smoke.py head_muscles
```

该测试显式允许下载，权重目录为 tools/model-cache。启动脚本使用相同缓存目录。若不希望等待，可事先从官方发布页下载并按上游规定放置完整权重，再在模块中保持“允许下载”不勾选。

## 独立审查

独立审查提出五项实质问题：自动基准可修改、病例混入场景包、失败导入可能清空场景、保存提前阻止后续推理、缺失类别不进入统计。以上已修改并加入真实 Slicer 回归检查。标签更新事件使用 representation-specific events，目标和裁剪模型均记录权重哈希。

## 交付边界

使用 Additional module paths 的扩展源码 ZIP 已打包；未测试 CMake 构建或 Extension Manager 发布。多结构重叠时阻止单层多标签研究包导出，可用 Slicer 自身 Save 保存无损场景。自动基准通过隐藏和指纹防止静默改变，不能防止有意通过 Python 脚本改写所有数据及指纹。
