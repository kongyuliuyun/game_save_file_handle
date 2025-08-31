import os
import zipfile
import tempfile
import shutil
from pathlib import Path

def scan_directories(root_path):
    """
    扫描指定文件夹下的所有子目录
    
    Args:
        root_path (str): 根目录路径
    
    Returns:
        list: 子目录列表
    """
    directories = []

    # 检查根目录是否存在
    if not os.path.exists(root_path):
        print(f"错误: 路径 {root_path} 不存在")
        return directories

    # 遍历根目录下的所有子目录
    for item in os.listdir(root_path):
        item_path = os.path.join(root_path, item)
        if os.path.isdir(item_path):
            directories.append(item_path)

    return directories

def package_directory(dir_path, output_dir):
    """
    将目录打包成ZIP文件
    
    Args:
        dir_path (str): 要打包的目录路径
        output_dir (str): ZIP文件输出目录
    
    Returns:
        str: 打包后的ZIP文件路径
    """
    dir_name = os.path.basename(dir_path)
    zip_filename = f"{dir_name}.zip"
    zip_filepath = os.path.join(output_dir, zip_filename)
    
    print(f"正在打包目录: {dir_name}")
    
    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                # 计算在ZIP中的相对路径
                arcname = os.path.relpath(file_path, dir_path)
                zipf.write(file_path, arcname)
                print(f"  已添加: {arcname}")
    
    print(f"打包完成: {zip_filepath}")
    return zip_filepath


def package_file(root_path, zip_path):
    """
    主函数
    
    Args:
        root_path (str): 要处理的根目录路径
    """
    print(f"正在扫描目录: {root_path}")
    print("-" * 50)


    # 扫描子目录
    subdirectories = scan_directories(root_path)

    if not subdirectories:
        print("未找到任何子目录")
        return

    os.makedirs(zip_path, exist_ok=True)
    # 打包并上传每个子目录
    for dir_path in subdirectories:
        dir_name = os.path.basename(dir_path)
        print(f"\n处理目录: {dir_name}")

        # 打包目录
        package_directory(dir_path, zip_path)


    print("\n所有目录已处理完成")


if __name__ == "__main__":
    # 使用示例
    # 请将下面的路径替换为您要处理的实际路径
    root_directory = "D:\MyDownload\game-save-backup"
    
    # 运行主函数
    package_file(root_directory)
    
    print("\n注意:")
    print("1. 请安装阿里云盘的SDK或使用其API来实现真实的上传功能")
    print("2. 可能需要身份验证和授权")
    print("3. 根据网络情况，上传可能需要较长时间")