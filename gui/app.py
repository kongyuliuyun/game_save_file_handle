import json
import os
import sys
import threading
import queue
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    from game_save_file_handle.core import game_scanner, dir_packager
    from game_save_file_handle.upload import baiduyun_upload
    from game_save_file_handle.utils.config_load import load_config, resolve_backup_path
except ImportError:
    from core import game_scanner, dir_packager
    from upload import baiduyun_upload
    from utils.config_load import load_config, resolve_backup_path


# ---------- 资源路径辅助 ----------

def _get_asset_path(filename):
    """获取资源文件路径，兼容开发环境和 PyInstaller 打包。"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, filename)
    else:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename)


# ---------- 主界面 ----------

class GameSaveGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("游戏存档备份工具")
        self.root.geometry("800x600")
        self.root.minsize(600, 500)

        self._set_window_icon()

        self.cfg = load_config()
        self.game_dirs = []
        self.is_running = False
        self.cancel_requested = False
        self.progress_queue = queue.Queue()

        self._build_ui()
        self._poll_progress_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_window_icon(self):
        """设置窗口图标（任务栏 + 标题栏）。"""
        icon_path = _get_asset_path(os.path.join('img', 'icon.ico'))
        try:
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
            else:
                self.root.iconbitmap('default')
        except Exception:
            pass

    # ==================== 构建 UI ====================

    def _build_ui(self):
        # Tab 容器
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # ---- Tab 1: 备份任务 ----
        self._build_backup_tab()

        # ---- Tab 2: 百度云授权 ----
        self._build_auth_tab()

    def _build_backup_tab(self):
        tab1 = ttk.Frame(self.notebook)
        self.notebook.add(tab1, text="备份任务")

        # Canvas + 滚动条
        outer = ttk.Frame(tab1)
        outer.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(outer, highlightthickness=0)
        self.v_scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas)

        self.content_id = self.canvas.create_window((0, 0), window=self.content, anchor=tk.NW)
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.content.bind("<Configure>", self._on_content_configure)
        self._bind_mousewheel()

        # ---- 文件夹选择 ----
        top_frame = ttk.LabelFrame(self.content, text="扫描目录", padding=5)
        top_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.folder_path = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.folder_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(top_frame, text="选择文件夹", command=self._select_folder).pack(side=tk.LEFT, padx=2)

        # ---- 分割区域 ----
        paned = ttk.PanedWindow(self.content, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 游戏列表
        list_frame = ttk.LabelFrame(paned, text="游戏文件夹列表", padding=5)
        paned.add(list_frame, weight=2)

        list_toolbar = ttk.Frame(list_frame)
        list_toolbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(list_toolbar, text="全选", command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(list_toolbar, text="取消全选", command=self._deselect_all).pack(side=tk.LEFT, padx=2)

        list_inner = ttk.Frame(list_frame)
        list_inner.pack(fill=tk.BOTH, expand=True)
        self.game_listbox = tk.Listbox(list_inner, selectmode=tk.MULTIPLE, exportselection=False)
        list_vsb = ttk.Scrollbar(list_inner, orient=tk.VERTICAL, command=self.game_listbox.yview)
        list_hsb = ttk.Scrollbar(list_inner, orient=tk.HORIZONTAL, command=self.game_listbox.xview)
        self.game_listbox.configure(yscrollcommand=list_vsb.set, xscrollcommand=list_hsb.set)
        self.game_listbox.grid(row=0, column=0, sticky="nsew")
        list_vsb.grid(row=0, column=1, sticky="ns")
        list_hsb.grid(row=1, column=0, sticky="ew")
        list_inner.grid_rowconfigure(0, weight=1)
        list_inner.grid_columnconfigure(0, weight=1)

        # 日志
        log_frame = ttk.LabelFrame(paned, text="日志", padding=5)
        paned.add(log_frame, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=6, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ---- 备份配置 ----
        cfg_frame = ttk.LabelFrame(self.content, text="备份配置", padding=5)
        cfg_frame.pack(fill=tk.X, padx=8, pady=4)

        row1 = ttk.Frame(cfg_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="备份路径:", width=10).pack(side=tk.LEFT)
        self.backup_path_var = tk.StringVar(value=resolve_backup_path(self.cfg.get("save_backup_path", "")))
        ttk.Entry(row1, textvariable=self.backup_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row1, text="浏览", command=lambda: self._browse_dir(self.backup_path_var)).pack(side=tk.LEFT)

        row2 = ttk.Frame(cfg_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="ZIP路径:", width=10).pack(side=tk.LEFT)
        self.zip_path_var = tk.StringVar(value=resolve_backup_path(self.cfg.get("zip_backup_path", "")))
        ttk.Entry(row2, textvariable=self.zip_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row2, text="浏览", command=lambda: self._browse_dir(self.zip_path_var)).pack(side=tk.LEFT)

        # ---- 进度条 ----
        progress_frame = ttk.LabelFrame(self.content, text="进度", padding=5)
        progress_frame.pack(fill=tk.X, padx=8, pady=4)

        ttk.Label(progress_frame, text="扫描进度:").pack(anchor=tk.W)
        self.scan_progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.scan_progress.pack(fill=tk.X, pady=(2, 6))

        ttk.Label(progress_frame, text="打包/上传进度:").pack(anchor=tk.W)
        self.pack_progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.pack_progress.pack(fill=tk.X, pady=2)

        # ---- 底部按钮 ----
        bottom_frame = ttk.Frame(self.content)
        bottom_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        self.execute_btn = ttk.Button(bottom_frame, text="执行备份", command=self._start_backup)
        self.execute_btn.pack(side=tk.LEFT, padx=2)

        self.cancel_btn = ttk.Button(bottom_frame, text="取消", command=self._cancel_backup, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=2)

    def _build_auth_tab(self):
        tab2 = ttk.Frame(self.notebook)
        self.notebook.add(tab2, text="百度云授权")

        frame = ttk.Frame(tab2, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="百度云 ByPy 授权",
                  font=("", 12, "bold")).pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(frame, text="1. 点击「获取授权链接」，自动在浏览器中打开百度授权页面\n"
                  "2. 登录百度账号，获取授权码\n"
                  "3. 将授权码粘贴到下方输入框\n"
                  "4. 点击「确认授权」完成",
                  wraplength=500).pack(anchor=tk.W, pady=(0, 8))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))
        self.auth_btn = ttk.Button(btn_frame, text="获取授权链接", command=self._start_auth)
        self.auth_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(frame, text="授权码:").pack(anchor=tk.W, pady=(8, 2))
        self.auth_code_var = tk.StringVar()
        code_frame = ttk.Frame(frame)
        code_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Entry(code_frame, textvariable=self.auth_code_var, width=40).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.confirm_btn = ttk.Button(code_frame, text="确认授权", command=self._confirm_auth, state=tk.DISABLED)
        self.confirm_btn.pack(side=tk.LEFT)

        ttk.Label(frame, text="状态:").pack(anchor=tk.W)
        self.auth_status = scrolledtext.ScrolledText(frame, height=8, state=tk.DISABLED, wrap=tk.WORD)
        self.auth_status.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    # ==================== Canvas 滚动辅助 ====================

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.content_id, width=event.width)

    def _on_content_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_mousewheel(self):
        def _on_wheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_enter(e):
            self.canvas.bind_all("<MouseWheel>", _on_wheel)
        def _on_leave(e):
            self.canvas.unbind_all("<MouseWheel>")
        self.canvas.bind("<Enter>", _on_enter)
        self.canvas.bind("<Leave>", _on_leave)

    def _on_close(self):
        if self.is_running:
            self.cancel_requested = True
            self._close_attempts = getattr(self, '_close_attempts', 0) + 1
            if self._close_attempts <= 3:
                self._log("正在取消任务，请稍后...\n")
                self.root.after(500, self._on_close)
            else:
                if messagebox.askyesno("强制关闭", "任务未能在超时内完成，是否强制退出？"):
                    self.root.destroy()
                else:
                    self._close_attempts = 0
        else:
            self.root.destroy()

    # ==================== 百度云授权 ====================

    # 百度 OAuth 常量（来自 bypy，程序内置无需外部安装）
    _BAIDU_APP_KEY = "q8WE4EpCsau1oS0MplgMKNBn"
    _BAIDU_SECRET_KEY = "PA4MhwB5RE7DacKtoP2i8ikCnNzAqYTD"
    _BAIDU_AUTH_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
    _BAIDU_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
    _TOKEN_PATH = os.path.join(os.path.expanduser("~"), ".bypy", "bypy.json")

    def _start_auth(self):
        """在浏览器中打开百度 OAuth 授权页面，并激活授权码输入。"""
        params = urllib.parse.urlencode({
            'client_id': self._BAIDU_APP_KEY,
            'response_type': 'code',
            'redirect_uri': 'oob',
            'scope': 'basic netdisk',
        })
        url = f"{self._BAIDU_AUTH_URL}?{params}"

        self._auth_log("正在打开浏览器授权页面...\n")
        self._auth_log(f"若浏览器未自动打开，请手动访问:\n{url}\n\n")

        try:
            webbrowser.open(url)
        except Exception:
            pass

        self.confirm_btn.configure(state=tk.NORMAL)
        self.auth_code_var.set("")
        self._auth_log("请将授权码粘贴到上方输入框，点击「确认授权」\n")

    def _confirm_auth(self):
        """使用授权码换取 access token 并保存。"""
        auth_code = self.auth_code_var.get().strip()
        if not auth_code or len(auth_code) < 16:
            messagebox.showwarning("提示", "请输入有效的授权码")
            return

        self.auth_btn.configure(state=tk.DISABLED)
        self.confirm_btn.configure(state=tk.DISABLED)
        self._auth_log("正在换取授权令牌...\n")

        thread = threading.Thread(target=self._exchange_token, args=(auth_code,), daemon=True)
        thread.start()

    def _exchange_token(self, auth_code):
        try:
            data = urllib.parse.urlencode({
                'grant_type': 'authorization_code',
                'code': auth_code,
                'client_id': self._BAIDU_APP_KEY,
                'client_secret': self._BAIDU_SECRET_KEY,
                'redirect_uri': 'oob',
            }).encode('utf-8')

            req = urllib.request.Request(self._BAIDU_TOKEN_URL, data=data, method='POST')
            resp = urllib.request.urlopen(req, timeout=30)
            token = json.loads(resp.read().decode('utf-8'))

            if 'error' in token:
                self.root.after(0, lambda: self._auth_log(
                    f"授权失败: {token.get('error_description', token['error'])}\n"))
                return

            # 保存 token 到 bypy 缓存目录
            os.makedirs(os.path.dirname(self._TOKEN_PATH), exist_ok=True)
            with open(self._TOKEN_PATH, 'w', encoding='utf-8') as f:
                json.dump(token, f, ensure_ascii=False, indent=2)

            self.root.after(0, lambda: self._auth_log(
                "授权成功！令牌已保存到本地。\n"
                f"缓存位置: {self._TOKEN_PATH}\n"
                "现在可切换到「备份任务」页面上传文件到百度云。\n"))

        except Exception as e:
            self.root.after(0, lambda: self._auth_log(f"授权过程出错: {e}\n"))
        finally:
            self.root.after(0, lambda: self.auth_btn.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self.confirm_btn.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self.auth_code_var.set(""))

    def _auth_log(self, msg):
        self.auth_status.configure(state=tk.NORMAL)
        self.auth_status.insert(tk.END, msg)
        self.auth_status.see(tk.END)
        self.auth_status.configure(state=tk.DISABLED)

    # ==================== 备份任务（原有逻辑） ====================

    def _select_folder(self):
        folder = filedialog.askdirectory(title="选择游戏根目录")
        if folder:
            self.folder_path.set(folder)
            self._refresh_game_list()

    def _browse_dir(self, var):
        folder = filedialog.askdirectory(title="选择目录")
        if folder:
            var.set(folder)

    def _refresh_game_list(self):
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showwarning("提示", "请先选择扫描目录")
            return

        self.game_listbox.delete(0, tk.END)

        if game_scanner.is_game_directory(folder):
            # 当前目录本身是游戏目录（含 .exe），只显示此目录
            self.game_dirs = [folder]
        else:
            # 当前目录是游戏父目录，列出其所有子目录
            self.game_dirs = game_scanner.scan_game_directories(folder)

        if not self.game_dirs:
            self._log("未找到子目录\n")
            return

        self._log(f"找到 {len(self.game_dirs)} 个子目录:\n")
        for d in self.game_dirs:
            self.game_listbox.insert(tk.END, os.path.basename(d))
            self._log(f"  {os.path.basename(d)}\n")

        self._select_all()

    def _select_all(self):
        self.game_listbox.select_set(0, tk.END)

    def _deselect_all(self):
        self.game_listbox.selection_clear(0, tk.END)

    def _log(self, message):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _start_backup(self):
        selected = self.game_listbox.curselection()
        if not selected:
            messagebox.showwarning("提示", "请选择至少一个游戏目录")
            return

        backup_path = self.backup_path_var.get().strip()
        zip_path = self.zip_path_var.get().strip()
        if not backup_path or not zip_path:
            messagebox.showwarning("提示", "请设置备份路径和ZIP路径")
            return

        selected_dirs = [self.game_dirs[i] for i in selected]

        self.is_running = True
        self.cancel_requested = False
        self._task_id = getattr(self, '_task_id', 0) + 1
        self.execute_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.scan_progress['value'] = 0
        self.pack_progress['value'] = 0
        self._log("=" * 50 + "\n")
        self._log("开始执行备份任务\n")

        thread = threading.Thread(target=self._run_backup_task,
                                  args=(selected_dirs, backup_path, zip_path, self._task_id),
                                  daemon=True)
        thread.start()

    def _cancel_backup(self):
        self.cancel_requested = True
        self.is_running = False
        self.execute_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)
        self._log("任务已取消\n")

    def _progress_callback(self, filename, status, message):
        self.progress_queue.put({
            'filename': filename,
            'status': status,
            'message': message
        })

    def _poll_progress_queue(self):
        try:
            while True:
                msg = self.progress_queue.get_nowait()
                status = msg['status']

                # 日志消息
                if status in ('scan_found', 'copy_file', 'scan_info', 'scan_dir',
                              'scan_done', 'scan_start', 'scan_skip', 'scan_warn',
                              'scan_copy', 'pack_info', 'upload_info'):
                    self._log(f"  {msg['message']}\n")

                # 打包进度上限
                elif status == 'pack_max':
                    self.pack_progress['maximum'] = msg.get('message', 0)
                    self.pack_progress['value'] = 0

                # 打包进度（message = 当前已打包文件数）
                elif status == 'pack_progress':
                    self.pack_progress['value'] = msg.get('message', 0)

                # 清理扫描进度
                elif status == 'scan_progress':
                    self.scan_progress['value'] = msg.get('value', 0)

                # 上传开始：切换为滚动进度条
                elif status == 'upload_start':
                    self.pack_progress.configure(mode='indeterminate')
                    self.pack_progress.start()

                # 上传结束：恢复正常模式并填满
                elif status == 'upload_done':
                    self.pack_progress.stop()
                    self.pack_progress.configure(mode='determinate', value=self.pack_progress['maximum'])

        except queue.Empty:
            pass
        self.root.after(100, self._poll_progress_queue)

    def _run_backup_task(self, selected_dirs, backup_path, zip_path, task_id):
        try:
            save_ext = self.cfg.get("save_extensions", {'.sav', '.save'})
            whitelist = self.cfg.get("white_list_root_path", {})
            root_path = self.folder_path.get().strip()

            if root_path not in whitelist:
                whitelist = {root_path: ['all']}

            total_dirs = len(selected_dirs)
            self.scan_progress['maximum'] = total_dirs
            all_results = []

            for i, game_dir in enumerate(selected_dirs):
                if self.cancel_requested:
                    self._progress_callback('', 'scan_info', '扫描已取消\n')
                    return

                game_name = os.path.basename(game_dir)
                self._progress_callback(game_name, 'scan_dir',
                                        f"正在处理 ({i + 1}/{total_dirs}): {game_name}")

                if not game_scanner._check_whitelist(root_path, game_dir, whitelist):
                    self._progress_callback(game_name, 'scan_skip', f"白名单未通过，跳过: {game_name}")
                    all_results.append({'game_dir': game_dir, 'status': 'skipped', 'save_count': 0,
                                        'error_msg': '白名单未通过'})
                    self.scan_progress['value'] = i + 1
                    continue

                save_parents = game_scanner.find_save_file_parent_dirs(
                    game_dir, save_ext, progress_callback=self._progress_callback)

                if not save_parents:
                    self._progress_callback(game_name, 'scan_warn', f"未找到存档文件: {game_name}")
                    all_results.append({'game_dir': game_dir, 'status': 'no_saves', 'save_count': 0,
                                        'error_msg': '未找到存档文件'})
                    self.scan_progress['value'] = i + 1
                    continue

                if game_dir in save_parents:
                    self._progress_callback(game_name, 'scan_warn', f"存档文件位于游戏目录根层，跳过: {game_name}")
                    all_results.append({'game_dir': game_dir, 'status': 'root_saves', 'save_count': 0,
                                        'error_msg': '存档文件与游戏目录相同'})
                    self.scan_progress['value'] = i + 1
                    continue

                self._progress_callback(game_name, 'scan_copy', "正在复制存档文件...")
                copied = game_scanner.package_save_files(
                    game_dir, save_parents, backup_path, save_ext,
                    progress_callback=self._progress_callback)
                self._progress_callback(game_name, 'scan_done', f"完成: {game_name}, 复制 {copied} 个文件")
                all_results.append({'game_dir': game_dir, 'status': 'ok', 'save_count': copied, 'error_msg': ''})
                self.scan_progress['value'] = i + 1

            ok_count = sum(1 for r in all_results if r['status'] == 'ok')
            total_files = sum(r['save_count'] for r in all_results)
            self._progress_callback('', 'scan_info',
                                    f"\n扫描完成: {ok_count}/{len(all_results)} 个游戏目录, 共 {total_files} 个文件\n")

            if self.cancel_requested or self._task_id != task_id:
                return

            self._progress_callback('', 'pack_info', "开始打包 ZIP...\n")
            dir_packager.package_file(backup_path, zip_path, progress_callback=self._progress_callback)

            if self.cancel_requested or self._task_id != task_id:
                return

            self._progress_callback('', 'upload_info', "开始上传到百度云...\n")
            self._progress_callback('', 'upload_start', '')
            try:
                baiduyun_upload.upload_to_baiduyun(zip_path, progress_callback=self._progress_callback)
            finally:
                self._progress_callback('', 'upload_done', '')

            if not self.cancel_requested and self._task_id == task_id:
                self._progress_callback('', 'scan_info', "清理临时文件...\n")
                game_scanner.remove_directory(backup_path)
                game_scanner.remove_directory(zip_path)
                self._progress_callback('', 'scan_info', "全部任务完成!\n")

        except Exception as e:
            self._progress_callback('', 'scan_info', f"错误: {e}\n")
        finally:
            if self._task_id == task_id:
                self._finish_task()

    def _finish_task(self):
        self.is_running = False
        self.root.after(0, lambda: self.execute_btn.configure(state=tk.NORMAL))
        self.root.after(0, lambda: self.cancel_btn.configure(state=tk.DISABLED))
        self._progress_callback('', 'scan_info', f"{'=' * 50}\n")


def main():
    root = tk.Tk()
    _ = GameSaveGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
