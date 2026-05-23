import os
import zipfile


def scan_directories(root_path):
    """
    扫描指定文件夹下的所有子目录
    """
    directories = []
    if not os.path.exists(root_path):
        return directories
    for item in os.listdir(root_path):
        item_path = os.path.join(root_path, item)
        if os.path.isdir(item_path):
            directories.append(item_path)
    return directories


def _count_files(root_path):
    """递归统计目录下文件总数。"""
    count = 0
    for root, dirs, files in os.walk(root_path):
        count += len(files)
    return count


def package_directory(dir_path, output_dir, progress_callback=None):
    """
    将目录打包成 ZIP 文件。
    """
    dir_name = os.path.basename(dir_path)
    zip_filename = f"{dir_name}.zip"
    zip_filepath = os.path.join(output_dir, zip_filename)

    def log(msg):
        if progress_callback:
            progress_callback('', 'pack_info', msg)

    log(f"正在打包: {dir_name}")

    packed = 0
    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, dir_path)
                zipf.write(file_path, arcname)
                packed += 1
                if progress_callback:
                    progress_callback(arcname, 'pack_progress', packed)

    log(f"打包完成: {zip_filepath} ({packed} 个文件)")
    return zip_filepath


def package_file(root_path, zip_path, progress_callback=None):
    """
    将 root_path 下的每个子目录分别打包成 ZIP 到 zip_path。
    """

    def log(msg):
        if progress_callback:
            progress_callback('', 'pack_info', msg)

    log(f"正在扫描备份目录: {root_path}")
    subdirectories = scan_directories(root_path)

    if not subdirectories:
        log("未找到任何子目录")
        return

    # 先统计总文件数，设置进度条上限
    total_files = 0
    for dir_path in subdirectories:
        total_files += _count_files(dir_path)

    if progress_callback:
        progress_callback('', 'pack_max', total_files)

    os.makedirs(zip_path, exist_ok=True)
    for dir_path in subdirectories:
        dir_name = os.path.basename(dir_path)
        log(f"处理目录: {dir_name}")
        package_directory(dir_path, zip_path, progress_callback)

    log("所有目录已打包完成")


if __name__ == "__main__":
    package_file("D:\\MyDownload\\game-save-backup", "D:\\MyDownload\\game-save-backup-zip")
