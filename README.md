# 星绘工坊 / StarCanvas

Windows 桌面生图应用，当前版本 **1.0.2**。通过本机 ComfyUI 引擎运行六个工作流，支持连续提交任务、按顺序生成、拖入参考图，以及多图编辑默认保持第一张参考图的输出尺寸。

## 下载安装

打开 [最新离线安装包](https://github.com/hansy1026/comfyui-imagen-app/releases/latest)，下载该版本的 EXE 和**全部**同名前缀 BIN 分卷，放在同一文件夹，然后运行 EXE。完整包约 31 GiB。`Source code` 下载项只是源码，不能代替离线安装包。

运行要求与安装步骤见 `安装说明.txt`；Release 附件 `install-guide.txt` 为同一份说明，`SHA256SUMS.txt` 可用于检查下载文件是否完整。

## 项目内容

- `app.py`：桌面界面、任务队列、内置引擎启动和图片保存。
- `workflows.py`：六个工作流的参数和 API 图构建逻辑。
- `assets/`：图标和界面背景。
- `生图app.spec`、`installer.iss`：EXE 与完整离线安装包构建配置。
- `licenses/`：随应用提供的第三方许可与声明。

源码仓库不包含模型权重、Python/ComfyUI 运行环境、生成图片、用户参考图、日志或安装包分卷。下载源码本身不能离线生图；完整离线安装包需要另外准备内置环境与模型。

## 本地开发

已验证环境：Windows、Python 3.13、NVIDIA RTX 3060 Laptop 6 GB。

```powershell
python -m pip install -r requirements.txt
$env:SHENGTU_COMFY_DIR = 'D:\生图app\StarCanvas\runtime\ComfyUI'
python app.py
```

`SHENGTU_COMFY_DIR` 应指向可用的 ComfyUI 目录；其同级 `python/python.exe` 为离线引擎的 Python。模型和节点需要与安装版一致。

```powershell
python app.py --self-test
```

自测检查工作流、队列、参数快照与拖放处理，需要 Windows 桌面会话，但不运行模型推理。

## 构建所需的本地文件

构建 EXE 需要 `requirements-build.txt` 中的依赖。现有 spec 从项目内的 `tkinterdnd2/tkdnd/win-x64` 收集拖放组件，因此先执行：

```powershell
python -m pip install -r requirements-build.txt
python -m pip install --no-deps --target . tkinterdnd2==0.6.3
python -m PyInstaller --noconfirm --clean 生图app.spec
```

完整离线包另需 Inno Setup、`payload/ComfyUI`、配套 Python 环境及 `installer.iss` 中列出的八个模型文件。当前安装脚本中的 `ComfyRoot`、`PythonRoot` 和输出路径为作者机器配置，其他机器构建前需修改。第三方完整运行环境未放入本源码仓库。

## 维护与自动同步

正式维护目录为作者电脑的 `D:\生图app\project`。GitHub 登录使用 Git Credential Manager，凭据不会写入仓库。发布账号固定为 `hansy1026`。

在项目目录建立被 Git 忽略的 `local-settings.json`：

```json
{
  "Python": "C:/Python313/python.exe",
  "ISCC": "C:/Program Files (x86)/Inno Setup 6/ISCC.exe",
  "ComfyRoot": "D:/ComfyUI",
  "PythonRoot": "D:/python",
  "PayloadRoot": "D:/build-payload/ComfyUI"
}
```

填写实际路径，准备拖放组件及依赖，更新 `CHANGELOG.md`，然后在 PowerShell 7 执行：

```powershell
./build-release.ps1 -Version 1.0.3
```

脚本自测、构建 EXE 和离线安装包后，自动提交并推送源码，创建版本草稿，上传并逐个核对附件的 SHA256，全部成功后公开 Release，最后删除本地旧版安装包。此流程在开发者电脑发布版本时运行，用户日常生图不会上传数据。

已完成构建而上传中断时，运行 `python publish.py` 重试；匹配的附件会跳过，不会重新上传。上传失败不会发布不完整的下载版本。更改源码后应递增版本号，不能覆盖已经发布的版本。网络和 GitHub 登录必须可用，自动同步失败会明确报错。

## 使用许可

应用免费分享。各模型及第三方依赖仍按各自许可使用，详见 `licenses/`。Qwen 工作流保留非商业研究/评估限制；Krea 工作流保留许可与人工审核流程。免费分享不代表所有模型可不受限制地商用。
