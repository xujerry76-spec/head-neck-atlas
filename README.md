# 头颈 CT 科研图谱 · Slicer MVP

本地 Windows 桌面工具，复用 3D Slicer 和 TotalSegmentator。独立 scripted module，未修改上游 Slicer 源码。

## 已实现的工作流

- 导入 DICOM、选择 CT，复用 Slicer 的滚动、窗宽窗位、平移、缩放和三平面视图。
- 子进程运行 `head_glands_cavities` / `head_muscles`；界面可继续浏览，并可取消。
- 默认显示左右眼球、腮腺、咬肌。其他模型输出仍保留，可在 Segment Editor 中查看。
- 当前轴位截面生成中文名称和引线；结构不存在时隐藏；可拖动文字、显示/隐藏结构、双击定位。
- 人工修正使用自动结果的独立副本。拖动文字不改变分割边界。
- 保存场景、原图及两份多标签 NIfTI、类别表、体积 CSV、运行参数与权重 SHA-256；新目录发布前校验全部文件。

## 本工作区启动

已准备的运行环境位于 `tools/Slicer`，上游扩展位于 `tools/extensions`。使用 PowerShell：

```powershell
.\scripts\start-slicer.ps1
```

启动会显示 Slicer 并选择“头颈 CT 科研图谱”模块。工具目录、依赖与患者病例不加入 Git，也不打包进扩展 ZIP。

也可双击项目根目录的 `Start-HeadNeckAtlas.cmd`。工作区启动脚本将模型缓存定向到 `tools/model-cache`。

## 安装到其他 Slicer

1. 安装官方稳定版 Slicer（本项目集成测试目标为 5.12.4）。
2. 通过 Extension Manager 安装 TotalSegmentator 扩展。若下载扩展源码，将其中 `TotalSegmentator` 文件夹也添加为模块路径。
3. 解压本项目 ZIP，在 Edit → Application Settings → Modules → Additional module paths 中添加 `HeadNeckAtlas` 文件夹，重启 Slicer。
4. 模型包要求 `TotalSegmentator==2.14.0`。在 Slicer Python 控制台安装依赖：

```python
slicer.util.pip_install('TotalSegmentator==2.14.0')
```

这是本项目固定的适配版本。上游扩展“升级依赖”可能改动版本，不要在已验证研究环境中自动升级。GPU 需要与 PyTorch 匹配的 NVIDIA 驱动和 CUDA 支持；没有 GPU 可以选择 CPU。完整模型推理可能较慢。

第一次运行需要目标模型和裁剪模型权重。模块默认禁止网络下载，缺权重会明确失败。勾选“允许本次运行下载缺失权重”后，模型在本地计算，权重从上游下载。推理 worker 禁用 TotalSegmentator 的匿名使用统计。模型包和权重许可不同，增加新任务前须重新核查许可。

## 使用

1. 点击“导入 DICOM”，用 Slicer DICOM 模块导入并加载自己的头颈 CT；返回 Research → 头颈 CT 科研图谱。
2. 选择 CT 输入。非 DICOM 体积必须通过按钮明确确认 CT 来源、原始 HU 和几何信息；MRI 不支持。外部变换必须先硬化。
3. 选择腺体/腔隙任务并运行，再选择肌肉任务并运行。未开始修正前可依次运行两项；每项在同一会话只运行一次。
4. 结构列表勾选显示、双击定位；拖动文字调整标签布局。切片锚点按分割重新计算。狭小视图会收起部分文字，结构列表仍可使用。
5. 点击“开始 / 继续人工修正”，使用 Segment Editor 的 Paint、Erase 等工具。完成后返回图谱模块。
6. 填写研究编号，保存到一个尚不存在的目录。打开研究包会替换当前场景，操作前保存未保存的修正。

自动结果留存供对照，修正只在副本上执行。自动节点在普通编辑选择器中隐藏，统计和导出前核验指纹；通过脚本修改基准会被检测并阻止导出。开始修正后不再追加模型任务，以避免自动覆盖人工结果；单纯保存不会阻止追加任务。重新推理可切换输入为“None”后重新选择 CT，开启新会话。

## 数据与限制

- 研究包的 `scene.mrb` 仅保存所选病例的影像、自动结果、修正副本及模块参数，排除其他已加载病例。导入不等于脱敏，分享前检查影像、DICOM 标识、场景属性与运行记录。
- 模型推理目录包含临时影像，完成或正常取消后清理；Slicer 崩溃时临时目录可能残留。
- 自动结果和修正结果以 `automatic.nii.gz` / `corrected.nii.gz` 导出。`class_map.json` 定义数值到结构名称的映射，体积单位 mL。
- 多结构重叠不能无损写入单层多标签文件：本版本会阻止研究包导出并显示原因。可使用 Slicer 的 Save 保存 `.mrb` 场景保留重叠，不能以覆盖规则静默丢弃结构。
- 不支持未硬化的外部变换、非 CT、多用户、PACS 和模型训练。
- 模型支持范围不等于截图所有结构；未训练类别不生成标签。软件检查通过不代表分割准确度或临床验证通过。
- CMake 文件用于 Slicer 开发者构建；交付 ZIP 采用 Additional module paths 安装，不是 Extension Manager 安装包。

## 验证

```powershell
python -m unittest discover -s tests -v
.\scripts\test-slicer.ps1 -SlicerPath 'C:\path\to\Slicer.exe'
```

独立测试只需 Python 和 NumPy。Slicer 测试使用合成 CT，验证修正隔离、研究包重开、中文标签和场景清理；不下载病例或权重。详细结果见 `docs/validation.md`。真实病例验收需 3–5 个脱敏头颈 CT，并由研究人员核对结构边界和左右方向。

## 上游与引用

- 3D Slicer：https://github.com/Slicer/Slicer
- SlicerTotalSegmentator：https://github.com/lassoan/SlicerTotalSegmentator
- TotalSegmentator：https://github.com/wasserth/TotalSegmentator

科研使用请按上游说明引用 Slicer、TotalSegmentator、nnU-Net 和具体头颈模型论文。上游源码与模型不包含在本项目分发包中。
