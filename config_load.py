import yaml


# 缓存配置数据，避免重复读取文件
_config = None


def load_config():
    global _config
    if _config is not None:
        return _config
    
    f = open("./config.yaml", "r", encoding="UTF-8")
    config_str = f.read()
    f.close()
    _config = yaml.safe_load(config_str)
    return _config


if __name__ == '__main__':
    save_extensions = load_config()["save_extensions"]
    white_list_root_path = load_config()["white_list_root_path"]
    scan_root_path_list = load_config()["scan_root_path_list"]
    save_backup_path = load_config()["save_backup_path"]
    zip_backup_path = load_config()["zip_backup_path"]
    print(f"save_extensions:{save_extensions}, type:{type(save_extensions)}")
    print(f"save_extensions:{white_list_root_path}, type:{type(white_list_root_path)}")
    print(f"save_extensions:{scan_root_path_list}, type:{type(scan_root_path_list)}")
    print(f"save_extensions:{save_backup_path}, type:{type(save_backup_path)}")
    print(f"save_extensions:{zip_backup_path}, type:{type(zip_backup_path)}")