import os
import shutil
from pathlib import Path

from game_save_file_handle import dir_packager, baiduyun_upload
from game_save_file_handle.config_load import load_config

# 常见的存档文件扩展名
save_extensions = load_config()["save_extensions"]

white_list_root_path: dict[str, list[str]] = load_config()["white_list_root_path"]


def scan_game_directories(root_path):
    """
    扫描指定文件夹下的所有游戏目录
    
    Args:
        root_path (str): 游戏根目录路径
    
    Returns:
        list: 游戏目录列表
    """
    game_dirs = []

    # 检查根目录是否存在
    if not os.path.exists(root_path):
        print(f"错误: 路径 {root_path} 不存在")
        return game_dirs

    # 遍历根目录下的所有子目录
    for item in os.listdir(root_path):
        item_path = os.path.join(root_path, item)
        if os.path.isdir(item_path):
            game_dirs.append(item_path)

    return game_dirs


def find_save_file_parent_dirs(game_dir):
    """
    在游戏目录中查找所有存档文件的上级目录
    
    Args:
        game_dir (str): 游戏目录路径
    
    Returns:
        set: 存档文件上级目录集合
    """
    save_parent_dirs = set()

    # 遍历游戏目录及其子目录
    for root, dirs, files in os.walk(game_dir):
        for file in files:
            # 检查文件扩展名是否为存档相关
            file_ext = Path(file).suffix.lower()
            if file_ext in save_extensions:
                # 添加存档文件的上级目录
                parent_dir = os.path.dirname(os.path.join(root, file))
                save_parent_dirs.add(parent_dir)

    return save_parent_dirs


# 新增功能：打包存档文件
def package_save_files(game_dir, save_parent_dirs, backup_path):
    """
    将游戏目录中的存档文件按原目录结构复制到输出目录
    
    Args:
        :param game_dir: 游戏目录路径
        :param save_parent_dirs: 存档文件上级目录集合
        :param backup_path: 备份文件的目录
    
    Returns:
        int: 复制的文件数量

    """

    copied_count = 0

    # 遍历存档文件的上级目录
    for parent_dir in save_parent_dirs:
        # 遍历该目录下的所有文件
        for file in os.listdir(parent_dir):
            file_path = os.path.join(parent_dir, file)
            # 检查是否为文件且扩展名是存档相关
            if os.path.isfile(file_path):
                file_ext = Path(file).suffix.lower()
                if file_ext in save_extensions:
                    # 计算相对于游戏目录的路径
                    rel_path = os.path.relpath(parent_dir, game_dir)

                    # 目标目录路径
                    if rel_path == '.':
                        dst_dir_path = backup_path
                    else:
                        parent_dir_name = os.path.basename(game_dir)
                        game_backup_path = os.path.join(backup_path, parent_dir_name)
                        dst_dir_path = os.path.join(game_backup_path, rel_path)

                    # 创建目标目录
                    os.makedirs(dst_dir_path, exist_ok=True)

                    # 目标文件路径
                    dst_file_path = os.path.join(dst_dir_path, file)

                    # 复制文件
                    shutil.copy2(file_path, dst_file_path)
                    copied_count += 1
                    print(f"  已复制: {os.path.relpath(file_path, game_dir)}")

    return copied_count


def scan_dir(root_path, backup_path):
    """
    主函数
    """
    # 获取命令行参数或使用默认路径
    # if len(sys.argv) > 1:
    #     root_path = sys.argv[1]
    # else:
    #     # 如果没有提供参数，使用当前目录下的games文件夹作为示例
    #     root_path = os.path.join(os.getcwd(), "games")

    print(f"正在扫描游戏根目录: {root_path}")
    print("-" * 50)

    # 扫描游戏目录
    game_directories = scan_game_directories(root_path)

    if not game_directories:
        print("未找到任何游戏目录")
        return

    error_save_msg_list = list()

    # 输出游戏目录并查找存档文件上级目录
    for game_dir in game_directories:

        if scan_dir_by_whitelist(root_path, game_dir, white_list_root_path):
            print("  游戏目录白名单通过")
        else:
            print("  游戏目录白名单未通过")
            continue
        print(f"游戏目录: {game_dir}")

        # 查找存档文件的上级目录
        save_parents = find_save_file_parent_dirs(game_dir)

        if save_parents:
            print("  存档文件的上级目录:")
            for parent_dir in sorted(save_parents):
                print(f"    {parent_dir}")
        else:
            error_save_msg_list.append(f"  未找到存档文件:{game_dir}")
            continue

        if save_parents.__contains__(game_dir):
            error_save_msg_list.append(f"  存档文件和游戏目录相同:{game_dir}")
            continue
        # 新增功能：打包存档文件
        print("  正在打包存档文件...")
        # output_dir = os.path.join(os.path.dirname(game_dir), f"{game_name}_saves_package")
        # 修改调用方式，传入已获取的存档文件父目录列表
        copied_files = package_save_files(game_dir, save_parents, backup_path)

    # 打印出所有没有存档文件的游戏目录
    for error_save_msg in error_save_msg_list:
        print(error_save_msg)

def remove_directory(path):
    """
    安全地删除目录及其所有内容

    Args:
        path (str): 要删除的目录路径
    """
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
            print(f"已删除目录: {path}")
        except Exception as e:
            print(f"删除目录 {path} 时出错: {e}")
    else:
        print(f"目录不存在，无需删除: {path}")


# 定义一个黑白名单方法 指定文件夹才会被扫描
def scan_dir_by_whitelist(root_path, game_dir, whitelist):
    whitelist = white_list_root_path.get(root_path)
    dir_name = os.path.basename(game_dir)
    if whitelist is None:
        return False
    if "all" in whitelist:
        return True
    if dir_name in whitelist:
        return True
    return False




if __name__ == "__main__":
    save_backup_path = load_config()["save_backup_path"]

    # scan_root_path = 'D:\MyDownload\Telegram'
    scan_root_path_list = load_config()["scan_root_path_list"]

    zip_backup_path = load_config()["zip_backup_path"]

    for scan_root_path in scan_root_path_list:
        print(f"正在扫描游戏根目录: {scan_root_path}")
        scan_dir(scan_root_path, save_backup_path)
        print("-" * 50)

    dir_packager.package_file(save_backup_path, zip_backup_path)


    baiduyun_upload.upload_to_baiduyun(zip_backup_path)

    remove_directory(save_backup_path)
    remove_directory(zip_backup_path)
