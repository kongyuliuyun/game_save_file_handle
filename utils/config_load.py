import os
import sys

import yaml

_config = None


def _get_default_config_path():
    """获取默认配置文件路径，兼容开发环境和 PyInstaller 打包后的环境。
    优先级: 1. exe 同目录 config.yaml (用户可编辑)
            2. PyInstaller 内部 config/config.yaml
            3. 开发环境 config/config.yaml"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        external = os.path.join(exe_dir, 'config.yaml')
        if os.path.exists(external):
            return external
        internal = os.path.join(sys._MEIPASS, 'config', 'config.yaml')
        if os.path.exists(internal):
            return internal
        return external
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, 'config', 'config.yaml')


def _get_base_dir():
    """获取基准目录：exe 所在目录（打包后）或项目根目录（开发时）。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_backup_path(path):
    """
    将配置路径转为绝对路径。
    - 相对路径 (./xxx) → 基于 exe/项目根目录解析
    - 绝对路径 → 校验盘符，不存在则回退到可用磁盘
    """
    if not path:
        return path

    # 相对路径 → 基于基准目录解析
    if path.startswith('./') or path.startswith('.\\'):
        path = os.path.join(_get_base_dir(), path[2:])
    elif not os.path.isabs(path):
        path = os.path.join(_get_base_dir(), path)

    # 盘符存在性校验
    drive = os.path.splitdrive(path)[0]
    if drive and not os.path.exists(drive + os.sep):
        cwd_drive = os.path.splitdrive(os.getcwd())[0] or 'C:'
        path = cwd_drive + path[len(drive):]

    return path


def load_config(config_path=None):
    """
    加载 YAML 配置文件，支持缓存。

    Args:
        config_path: 配置文件路径，为 None 时使用默认路径
    """
    global _config
    if _config is not None:
        return _config

    path = config_path or _get_default_config_path()

    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, 'r', encoding='UTF-8') as f:
        _config = yaml.safe_load(f.read())
    return _config


def reload_config(config_path=None):
    """强制重新加载配置（清除缓存）"""
    global _config
    _config = None
    return load_config(config_path)


if __name__ == '__main__':
    cfg = load_config()
    for key, value in cfg.items():
        print(f"{key}: {value}, type: {type(value)}")
