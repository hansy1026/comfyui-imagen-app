#ifndef ComfyRoot
#define ComfyRoot "D:\qiuye_comfyui\ComfyUI-aki-v3\ComfyUI-aki-v3\ComfyUI"
#endif
#ifndef PythonRoot
#define PythonRoot "D:\qiuye_comfyui\ComfyUI-aki-v3\ComfyUI-aki-v3\python"
#endif
#ifndef PayloadRoot
#define PayloadRoot "payload\ComfyUI"
#endif

[Setup]
AppId=StarCanvasOffline
AppName=星绘工坊
AppVersion=1.0.2
AppPublisher=星绘工坊社区分享
DefaultDirName={%LOCALAPPDATA}\Programs\StarCanvas
DefaultGroupName=星绘工坊
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
SetupArchitecture=x64
MinVersion=10.0
WizardStyle=modern
LicenseFile=licenses\INSTALL-LICENSE.txt
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\生图app.exe
OutputBaseFilename=StarCanvas-Offline-Setup-1.0.2
DiskSpanning=yes
DiskSliceSize=2000000000
Compression=none
SolidCompression=no
#ifdef QUICK_BUILD
OutputDir=smoke
Uninstallable=no
#else
OutputDir=D:\生图app\离线安装包
#endif

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "dist\生图app.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\preview_art.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\app.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "workflows.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "tkinterdnd2\*"; DestDir: "{app}\source\tkinterdnd2"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
#ifndef QUICK_BUILD
Source: "{#PayloadRoot}\*"; DestDir: "{app}\runtime\ComfyUI"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PythonRoot}\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#ComfyRoot}\models\diffusion_models\qwen_image_2.1_int8_convrot.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\diffusion_models"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\unet\Krea-2-Turbo-Q3_K_M-3.91bpw.gguf"; DestDir: "{app}\runtime\ComfyUI\models\unet"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\text_encoders\qwen3vl_8b_w4a8.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\text_encoders"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\text_encoders\qwen3vl_4b_fp8_scaled.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\text_encoders"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\vae\qwen_image_2.1_vae_bf16.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\vae"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\vae\qwen_image_vae.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\vae"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\loras\krea2_style_reference.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\loras"; Flags: ignoreversion
Source: "{#ComfyRoot}\models\loras\krea2_sunsetblur.safetensors"; DestDir: "{app}\runtime\ComfyUI\models\loras"; Flags: ignoreversion
#endif

[Icons]
#ifndef QUICK_BUILD
Name: "{autoprograms}\星绘工坊"; Filename: "{app}\生图app.exe"
Name: "{autodesktop}\星绘工坊"; Filename: "{app}\生图app.exe"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\生图app.exe"; Description: "启动星绘工坊"; Flags: nowait postinstall skipifsilent
