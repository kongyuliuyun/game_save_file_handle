import os

from bypy import ByPy


def upload_to_baiduyun(filepath):
     """
     上传ZIP文件到百度云盘（模拟实现）
     注意：实际使用时需要替换为百度云盘的SDK或API调用

     Args:
         filepath (str): ZIP文件路径
     """
     bypy = ByPy()
     print("************************************")
     print("开始备份至百度云")
     # bypy.upload("D:\MyProject\PyCharm\game_save_file_handle\README.md","README.md")
     bypy.verbose = True
     bypy.syncup(filepath, os.path.basename(filepath))
     print("备份至百度云完成")
     print("************************************")



if __name__ == '__main__':
    upload_to_baiduyun("D:\MyDownload\game-save-backup-zip")