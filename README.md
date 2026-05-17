# 游戏存档备份工具

扫描指定目录下的游戏存档文件，备份并上传至百度云盘。

## 项目结构

```
game_save_file_handle/
├── .gitignore
├── README.md
├── requirements.txt
├── __init__.py
├── run_gui.py                   # GUI 启动入口
│
├── config/                      # 配置文件
│   └── config.yaml              # 应用配置
│
├── core/                        # 核心逻辑
│   ├── __init__.py
│   ├── game_scanner.py          # 游戏目录扫描、存档查找与复制
│   └── dir_packager.py          # 备份目录 ZIP 打包
│
├── gui/                         # 图形界面
│   ├── __init__.py
│   └── app.py                   # tkinter GUI（备份任务 + 百度云授权双标签页）
│
├── upload/                      # 上传模块
│   ├── __init__.py
│   └── baiduyun_upload.py       # 百度云上传
│
├── utils/                       # 工具
│   ├── __init__.py
│   └── config_load.py           # 配置文件加载、路径校验
│
├── scripts/                     # 构建 & 工具脚本
│   ├── build_exe.bat            # 一键打包 EXE
│   └── fix_icon.py              # EXE 图标注入工具
│
├── img/                         # 图标资源
│   └── icon.ico
│
└── dist/                        # 构建输出（gitignore）
    └── GameSaveBackup.exe
```

## 环境要求

- Python 3.8+
- Windows 10 / 11

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖项：
- **PyYAML** — 配置文件解析
- **ByPy** — 百度云盘 Python SDK
- **PyInstaller** — 打包为 EXE（仅打包时需要）

### 2. 百度云授权

首次使用需先完成百度账号 OAuth 授权：

**方式一（推荐）：通过 GUI**
启动程序后切换到「百度云授权」标签页，点击按钮弹出命令行窗口，按提示完成授权。

**方式二：手动命令行**
```bash
bypy list
```
执行后输出授权链接 → 浏览器打开 → 登录百度账号 → 获取授权码 → 粘贴回命令行。

> 授权令牌缓存于 `%USERPROFILE%\.bypy`，成功后无需重复操作。

## 配置文件 `config/config.yaml`

```yaml
# 存档文件扩展名
save_extensions : {'.sav', '.save', '.esm', '.esp', '.bsa', '.ba2', '.rpgsave', '.rmmzsave', '.phxsav'}

# 扫描白名单（路径 -> 允许的游戏名列表，"all" 表示全部允许）
white_list_root_path : {'default': ['all']}

# 备份输出目录（相对路径 = exe 同目录下）
save_backup_path : './game-save-backup'

# 压缩包输出目录
zip_backup_path : './game-save-backup-zip'
```

| 配置项 | 说明 |
|--------|------|
| `save_extensions` | 识别为存档文件的扩展名（需含点号） |
| `white_list_root_path` | 按根目录配置白名单，`all` 全部放行 |
| `save_backup_path` | 存档备份临时目录，上传后自动清理 |
| `zip_backup_path` | ZIP 压缩包临时目录，上传后自动清理 |

> **路径智能解析**：相对路径（如 `./backup`）自动基于 exe 所在目录解析；绝对路径若盘符不存在则自动回退到可用磁盘。

## 使用方式

### 图形界面（推荐）

```bash
cd <项目父目录>
python -m game_save_file_handle.run_gui
```

界面包含两个标签页：

**备份任务** — 主要功能
1. 点击「选择文件夹」选择游戏根目录
2. 点击「扫描子目录」列出所有游戏文件夹（支持全选/反选）
3. 勾选需要备份的游戏
4. 设置备份路径和 ZIP 路径（默认值来自 config.yaml，已自动校验盘符）
5. 点击「执行备份」，实时查看扫描进度和上传进度

**百度云授权** — 首次使用
1. 点击按钮弹出命令行窗口
2. 浏览器打开授权链接 → 登录 → 获取授权码 → 粘贴回命令行
3. 授权完成后切换到备份任务页面上传

> 界面支持窗口缩放，游戏列表和日志区域可拖拽分割，小窗口下外层自动出现滚动条。

### 命令行

```bash
cd <项目父目录>
python -m game_save_file_handle.core.game_scanner
```

读取 `config/config.yaml` 中的 `scan_root_path_list` 并依次处理。

## 打包为 EXE

```bash
scripts\build_exe.bat
```

脚本自动执行：
1. 创建干净 venv 环境（避免 Anaconda pathlib 冲突）
2. 安装 PyYAML + ByPy + PyInstaller
3. 打包为单文件 `GameSaveBackup.exe`（含 tkinter、ByPy 资源、OpenSSL DLL）
4. 注入自定义图标（exe 文件图标 + 任务栏图标）

输出：`dist\GameSaveBackup.exe`

> 将 `config.yaml` 放在 exe 同目录下即可自定义配置，未放置则使用内嵌默认配置。

## 更换图标

1. 将图标保存为 `img\icon.png`
2. 转换为 ICO：
   ```bash
   pip install Pillow
   python -c "from PIL import Image; img=Image.open('img/icon.png'); img.save('img/icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)], bitmap_format='bmp')"
   ```
3. 运行 `build_exe.bat`

## 常见问题

**Q: 运行时提示 `_tkinter` 找不到？**
使用 `build_exe.bat` 打包，脚本已自动处理 Tcl/Tk DLL。

**Q: 上传报 SSL 错误？**
使用 `build_exe.bat` 打包，脚本已自动打包 OpenSSL DLL。

**Q: 备份路径在当前磁盘不存在？**
路径解析会自动检测盘符，不存在则回退到可用磁盘。

**Q: ByPy 授权过期？**
切换到「百度云授权」标签页重新执行授权流程。

**Q: 存档文件未被扫描到？**
检查 `config.yaml` 中 `save_extensions` 是否包含目标扩展名（需含点号，如 `.sav`）。
