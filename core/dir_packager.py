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


def package_directory(dir_path, output_dir, progress_callback=None):
    """
    将目录打包成 ZIP 文件。

    Args:
        dir_path: 要打包的目录路径
        output_dir: ZIP 文件输出目录
        progress_callback: 进度回调函数 (filename: str, status: str, message: str)
    Returns:
        str: 打包后的 ZIP 文件路径
    """
    dir_name = os.path.basename(dir_path)
    zip_filename = f"{dir_name}.zip"
    zip_filepath = os.path.join(output_dir, zip_filename)

    def log(msg):
        if progress_callback:
            progress_callback('', 'pack_info', msg)

    log(f"正在打包目录: {dir_name}")

    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, dir_path)
                zipf.write(file_path, arcname)
                if progress_callback:
                    progress_callback(arcname, 'pack_progress', f"已添加: {arcname}")

    log(f"打包完成: {zip_filepath}")
    return zip_filepath


def package_file(root_path, zip_path, progress_callback=None):
    """
    将 root_path 下的每个子目录分别打包成 ZIP 到 zip_path。
    """
    def log(msg):
        if progress_callback:
            progress_callback('', 'pack_info', msg)

    log(f"正在扫描目录: {root_path}")
    subdirectories = scan_directories(root_path)

    if not subdirectories:
        log("未找到任何子目录")
        return

    os.makedirs(zip_path, exist_ok=True)
    for dir_path in subdirectories:
        dir_name = os.path.basename(dir_path)
        log(f"处理目录: {dir_name}")
        package_directory(dir_path, zip_path, progress_callback)

    log("所有目录已打包完成")


if __name__ == "__main__":
    package_file("D:\\MyDownload\\game-save-backup", "D:\\MyDownload\\game-save-backup-zip")
