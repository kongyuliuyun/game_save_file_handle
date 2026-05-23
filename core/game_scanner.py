import os
import shutil
from pathlib import Path

try:
    from game_save_file_handle.utils.config_load import load_config, resolve_backup_path
except ImportError:
    from utils.config_load import load_config, resolve_backup_path


def _default_log(msg):
    """默认日志输出（CLI 模式）"""
    print(msg)


def scan_game_directories(root_path):
    """
    扫描指定文件夹下的所有子目录（游戏目录）。
    同时检查根目录本身是否包含存档文件，如果包含则将其也加入列表。
    """
    game_dirs = []
    if not os.path.exists(root_path):
        return game_dirs
    for item in os.listdir(root_path):
        item_path = os.path.join(root_path, item)
        if os.path.isdir(item_path):
            game_dirs.append(item_path)
    return game_dirs


def is_game_directory(directory):
    """检查目录直接包含 .exe 文件，若是则判定为游戏目录。"""
    if not os.path.exists(directory):
        return False
    for item in os.listdir(directory):
        if item.lower().endswith('.exe'):
            return True
    return False


def find_save_file_parent_dirs(game_dir, save_extensions, progress_callback=None):
    """
    在游戏目录中查找所有包含存档文件的父目录。

    Returns:
        set: 存档文件父目录集合
    """
    save_parent_dirs = set()
    log = progress_callback or (lambda fn, st, msg: None)

    for root, dirs, files in os.walk(game_dir):
        for file in files:
            file_ext = Path(file).suffix.lower()
            if file_ext in save_extensions:
                parent_dir = os.path.dirname(os.path.join(root, file))
                save_parent_dirs.add(parent_dir)
                log(file, 'scan_found', f"发现存档: {os.path.relpath(os.path.join(root, file), game_dir)}")
    return save_parent_dirs


def package_save_files(game_dir, save_parent_dirs, backup_path, save_extensions, progress_callback=None):
    """
    将游戏目录中的存档文件按原目录结构复制到备份目录。

    Returns:
        int: 复制的文件数量
    """
    copied_count = 0
    log = progress_callback or (lambda fn, st, msg: None)

    for parent_dir in save_parent_dirs:
        for file in os.listdir(parent_dir):
            file_path = os.path.join(parent_dir, file)
            if os.path.isfile(file_path):
                file_ext = Path(file).suffix.lower()
                if file_ext in save_extensions:
                    rel_path = os.path.relpath(parent_dir, game_dir)

                    if rel_path == '.':
                        dst_dir_path = backup_path
                    else:
                        parent_dir_name = os.path.basename(game_dir)
                        game_backup_path = os.path.join(backup_path, parent_dir_name)
                        dst_dir_path = os.path.join(game_backup_path, rel_path)

                    os.makedirs(dst_dir_path, exist_ok=True)
                    dst_file_path = os.path.join(dst_dir_path, file)
                    shutil.copy2(file_path, dst_file_path)
                    copied_count += 1
                    log(file, 'copy_file', f"已复制: {os.path.relpath(file_path, game_dir)}")

    return copied_count


def scan_dir(root_path, backup_path, save_extensions, whitelist_dict,
             progress_callback=None):
    """
    扫描指定根目录下的所有游戏目录，查找并复制存档文件。

    Returns:
        list[dict]: 每个游戏目录的扫描结果 [{game_dir, status, save_count, error_msg}]
    """
    log = progress_callback or (lambda fn, st, msg: None)

    log('', 'scan_start', f"开始扫描: {root_path}")
    game_directories = scan_game_directories(root_path)

    if not game_directories:
        log('', 'scan_warn', "未找到任何子目录（游戏目录）")
        return []

    results = []

    for i, game_dir in enumerate(game_directories):
        game_name = os.path.basename(game_dir)
        log(game_name, 'scan_dir', f"正在检查游戏目录 ({i + 1}/{len(game_directories)}): {game_name}")

        if not _check_whitelist(root_path, game_dir, whitelist_dict):
            log(game_name, 'scan_skip', f"白名单未通过，跳过: {game_name}")
            results.append({'game_dir': game_dir, 'status': 'skipped', 'save_count': 0,
                            'error_msg': '白名单未通过'})
            continue

        save_parents = find_save_file_parent_dirs(game_dir, save_extensions, progress_callback)

        if not save_parents:
            log(game_name, 'scan_warn', f"未找到存档文件: {game_name}")
            results.append({'game_dir': game_dir, 'status': 'no_saves', 'save_count': 0,
                            'error_msg': '未找到存档文件'})
            continue

        if game_dir in save_parents:
            log(game_name, 'scan_warn', f"存档文件位于游戏目录根层，跳过: {game_name}")
            results.append({'game_dir': game_dir, 'status': 'root_saves', 'save_count': 0,
                            'error_msg': '存档文件与游戏目录相同'})
            continue

        log(game_name, 'scan_copy', f"正在复制存档文件...")
        copied = package_save_files(game_dir, save_parents, backup_path, save_extensions, progress_callback)
        log(game_name, 'scan_done', f"完成: {game_name}, 复制 {copied} 个文件")
        results.append({'game_dir': game_dir, 'status': 'ok', 'save_count': copied, 'error_msg': ''})

    return results


def _check_whitelist(root_path, game_dir, whitelist_dict):
    """检查游戏目录是否在白名单中。"""
    whitelist = whitelist_dict.get(root_path)
    dir_name = os.path.basename(game_dir)
    if whitelist is None:
        return False
    if "all" in whitelist:
        return True
    if dir_name in whitelist:
        return True
    return False


def remove_directory(path):
    """安全删除目录。"""
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
        except Exception:
            pass


if __name__ == "__main__":
    cfg = load_config()
    save_ext = cfg["save_extensions"]
    whitelist = cfg.get("white_list_root_path", {})
    save_backup = resolve_backup_path(cfg["save_backup_path"])
    zip_backup = resolve_backup_path(cfg["zip_backup_path"])
    scan_root_path_list = cfg.get("scan_root_path_list", set())

    for scan_root in scan_root_path_list:
        print(f"正在扫描: {scan_root}")
        scan_dir(scan_root, save_backup, save_ext, whitelist)

    try:
        from game_save_file_handle.core import dir_packager
        from game_save_file_handle.upload import baiduyun_upload
    except ImportError:
        from core import dir_packager
        from upload import baiduyun_upload

    dir_packager.package_file(save_backup, zip_backup)
    baiduyun_upload.upload_to_baiduyun(zip_backup)

    remove_directory(save_backup)
    remove_directory(zip_backup)
