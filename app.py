"""Windows desktop front end for the user's local ComfyUI workflows."""

import io
import json
import mimetypes
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Y, Canvas, StringVar, BooleanVar, Text, filedialog, messagebox
from tkinter import ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from workflows import WORKFLOWS, build_prompt, coerce, defaults, image_fields, qwen_size, self_test


APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DEFAULT_COMFY = Path(os.environ.get("SHENGTU_COMFY_DIR", APP_DIR / "runtime" / "ComfyUI"))
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "生图app"
DEFAULT_OUTPUT = Path("D:/生图app/生成图片") if Path("D:/").exists() else Path.home() / "Pictures" / "生图app"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
GROUPS = ("创作内容", "参考图片", "画面尺寸", "采样控制", "模型与编码", "输出文件")
BG, SIDEBAR, CARD, INPUT = "#0d1226", "#101832", "#1a2340", "#222d4e"
TEXT, MUTED, ACCENT, TEAL = "#f2f3ff", "#aab4d1", "#aa9aff", "#7ee1d3"
FLOW_DESCRIPTIONS = {
    "qwen": "自由描述画面，细调构图、采样与输出。",
    "krea": "快速探索具有艺术质感的画面。",
    "qwen_edit": "融合 1–6 张参考图，保持人物、商品或服装一致。",
    "qwen_alpha": "生成透明 PNG，或上传图片抠出主体。",
    "krea_style": "从参考图片提取色彩、光线与材质风格。",
    "krea_cinema": "用 sunsetblur LoRA 创作柔和电影感画面。",
}


def request_json(url, payload=None, timeout=20):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", "replace")[:1600]
        raise RuntimeError(f"ComfyUI 返回 HTTP {exc.code}：{details}") from exc


def upload_image(server, path):
    path = Path(path)
    boundary = "----ComfyUI" + uuid.uuid4().hex
    filename = uuid.uuid4().hex + path.suffix.lower()
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(server + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"上传 {path.name} 失败：{exc.read().decode('utf-8', 'replace')[:800]}") from exc
    if not result.get("name"):
        raise RuntimeError(f"上传 {path.name} 后未收到文件名")
    return result["name"]


def options_from_server(server):
    sources = {
        "UNETLoader": ("unet_name", "weight_dtype"),
        "UnetLoaderGGUF": ("unet_name",),
        "CLIPLoader": ("clip_name", "clip_type", "clip_device"),
        "VAELoader": ("vae_name",),
        "KSampler": ("sampler_name", "scheduler"),
    }
    choices = {"qwen": {}, "krea": {}}
    for node_type, keys in sources.items():
        try:
            info = request_json(f"{server}/object_info/{node_type}", timeout=15)[node_type]
            inputs = info["input"]["required"]
            for key in keys:
                api_key = {"clip_type": "type", "clip_device": "device"}.get(key, key)
                definition = inputs.get(api_key)
                if definition and isinstance(definition[0], list):
                    values = tuple(map(str, definition[0]))
                    for flow in ("qwen", "krea"):
                        if node_type == "UNETLoader" and flow != "qwen":
                            continue
                        if node_type == "UnetLoaderGGUF" and flow != "krea":
                            continue
                        choices[flow][key] = values
        except (KeyError, RuntimeError, urllib.error.URLError, TimeoutError):
            continue
    return choices


def match_reference_size(graph, width, height):
    graph["490"] = {"class_type": "ImageScale", "inputs": {"image": ["457", 0],
        "upscale_method": "lanczos", "width": width, "height": height, "crop": "disabled"}}
    if "460" in graph:
        graph["460"]["inputs"]["image"] = ["490", 0]
    else:
        graph["461"]["inputs"]["images"] = ["490", 0]


class App:
    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.root.title("星绘工坊 · 离线生图")
        self.root.geometry("1390x870")
        self.root.minsize(1080, 700)
        self.root.configure(background=BG)
        icon = APP_DIR / "assets" / "app.ico"
        if icon.is_file():
            self.root.iconbitmap(str(icon))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.task_queue = queue.Queue()
        self.task_errors = {}
        self.pending_jobs = 0
        self.next_job_id = 1
        self.busy = False
        self.server_process = None
        self.server_log = None
        self.server_url = None
        self.choices = {"qwen": {}, "krea": {}}
        self.values = {flow: defaults(flow) for flow in WORKFLOWS}
        self.active_flow = "qwen"
        self.vars = {}
        self.widgets = {}
        self.file_buttons = {}
        self.fields = {}
        self.preview_photo = None
        self.result_paths = []
        self.pending_review = []
        style = ttk.Style(self.root)
        style.theme_use("clam")
        font = "Microsoft YaHei UI"
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=(font, 10))
        style.configure("Sidebar.TFrame", background=SIDEBAR)
        style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=TEXT, font=(font, 10))
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=(font, 10))
        style.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=(font, 9))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(font, 10))
        style.configure("Preview.TLabel", background=CARD, foreground=MUTED)
        style.configure("TLabelframe", background=CARD, bordercolor="#354164", borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=(font, 11, "bold"))
        style.configure("TEntry", fieldbackground=INPUT, foreground=TEXT, bordercolor="#445277", padding=6)
        style.configure("TCombobox", fieldbackground=INPUT, foreground=TEXT, background=INPUT, bordercolor="#445277", padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT)], foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=(font, 10))
        style.map("TCheckbutton", background=[("active", CARD)], foreground=[("active", TEXT)])
        style.configure("Nav.TButton", background=SIDEBAR, foreground=MUTED, borderwidth=0,
                        padding=(16, 13), anchor="w", font=(font, 11))
        style.configure("NavActive.TButton", background="#303960", foreground=TEXT, borderwidth=0,
                        padding=(16, 13), anchor="w", font=(font, 11, "bold"))
        style.map("Nav.TButton", background=[("active", "#232d50")], foreground=[("active", TEXT)])
        style.configure("Primary.TButton", background=ACCENT, foreground="#11152c", borderwidth=0,
                        padding=(12, 12), font=(font, 12, "bold"))
        style.map("Primary.TButton", background=[("active", "#c0b6ff")])
        style.configure("TButton", background="#303a5e", foreground=TEXT, padding=(9, 7), font=(font, 10))
        style.map("TButton", background=[("active", "#45527b")])
        style.configure("Treeview", background=INPUT, fieldbackground=INPUT, foreground=TEXT,
                        borderwidth=0, rowheight=28, font=(font, 9))
        style.configure("Treeview.Heading", background="#303a5e", foreground=TEXT, font=(font, 9, "bold"))
        style.configure("TProgressbar", background=TEAL, troughcolor=INPUT)

        outer = ttk.Frame(self.root, padding=(0, 0, 18, 16))
        outer.pack(fill=BOTH, expand=True)
        sidebar = ttk.Frame(outer, style="Sidebar.TFrame", width=242, padding=(16, 20))
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="✦ 星绘工坊", style="Sidebar.TLabel", foreground=TEXT,
                  font=(font, 20, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(sidebar, text="OFFLINE  CREATIVE STUDIO", style="Sidebar.TLabel",
                  foreground=TEAL, font=(font, 8, "bold")).pack(anchor="w", pady=(0, 30))
        ttk.Label(sidebar, text="创作模式", style="Sidebar.TLabel", foreground=MUTED,
                  font=(font, 9, "bold")).pack(anchor="w", padx=10, pady=(0, 9))
        self.nav_buttons = {}
        nav_names = {"qwen": "✦  自由生图", "krea": "✦  Krea2 生图",
                     "qwen_edit": "✦  多参考图编辑", "qwen_alpha": "✦  透明背景",
                     "krea_style": "✦  参考风格迁移", "krea_cinema": "✦  高级电影感"}
        for flow in WORKFLOWS:
            button = ttk.Button(sidebar, text=nav_names[flow], style="Nav.TButton",
                                command=lambda chosen=flow: self.set_flow(chosen))
            button.pack(fill=X, pady=3)
            self.nav_buttons[flow] = button
        self.connect_button = ttk.Button(sidebar, text="检查引擎与模型", command=self.connect)
        self.connect_button.pack(fill=X, padx=5, pady=(20, 0))
        ttk.Frame(sidebar, style="Sidebar.TFrame").pack(fill=BOTH, expand=True)
        ttk.Label(sidebar, text="●  完全本地运行", style="Sidebar.TLabel", foreground=TEAL,
                  font=(font, 10, "bold")).pack(anchor="w", padx=10, pady=(0, 9))
        ttk.Label(sidebar, text="Qwen Image 2.1 仅供非商业研究与评估；Krea2 依其社区许可使用。",
                  style="Sidebar.TLabel", foreground=MUTED, wraplength=205,
                  justify="left", font=(font, 9)).pack(anchor="w", padx=10, pady=(0, 16))

        content = ttk.Frame(outer, padding=(18, 20, 0, 0))
        content.pack(side=LEFT, fill=BOTH, expand=True)
        left = ttk.Frame(content, padding=(0, 0, 14, 0))
        left.pack(side=LEFT, fill=BOTH, expand=True)
        right = ttk.Frame(content, style="Card.TFrame", width=424, padding=16)
        right.pack(side=RIGHT, fill=Y)
        right.pack_propagate(False)
        self.flow_label = StringVar(value=WORKFLOWS["qwen"]["name"])
        self.flow_title = StringVar(value=self.flow_label.get())
        self.flow_desc = StringVar(value=FLOW_DESCRIPTIONS["qwen"])
        ttk.Label(left, text="创作面板", foreground=TEAL,
                  font=(font, 9, "bold")).pack(anchor="w")
        ttk.Label(left, textvariable=self.flow_title, font=(font, 19, "bold")).pack(anchor="w", pady=(4, 2))
        ttk.Label(left, textvariable=self.flow_desc, style="Muted.TLabel",
                  wraplength=590).pack(anchor="w", pady=(0, 15))

        self.canvas = Canvas(left, highlightthickness=0, background=BG)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.form = ttk.Frame(self.canvas)
        self.form_window = self.canvas.create_window((0, 0), window=self.form, anchor="nw")
        self.form.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.form_window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self.scroll_form)

        ttk.Label(right, text="画面预览", style="Card.TLabel",
                  font=(font, 14, "bold")).pack(anchor="w")
        self.preview = ttk.Label(right, text="生成完成后在这里预览", style="Preview.TLabel", anchor="center")
        self.preview.pack(fill=BOTH, expand=True, pady=(10, 12))
        art_path = APP_DIR / "assets" / "preview_art.png"
        if art_path.is_file():
            with Image.open(art_path) as art:
                art.thumbnail((320, 325))
                self.preview_photo = ImageTk.PhotoImage(art.convert("RGB"))
            self.preview.configure(image=self.preview_photo, text="")
        ttk.Label(right, text="保存位置", style="Card.TLabel").pack(anchor="w")
        output_row = ttk.Frame(right, style="Card.TFrame")
        output_row.pack(fill=X, pady=(5, 10))
        self.output_var = StringVar(value=str(DEFAULT_OUTPUT))
        ttk.Entry(output_row, textvariable=self.output_var).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(output_row, text="选择…", command=self.choose_output).pack(side=RIGHT, padx=(6, 0))
        self.generate_button = ttk.Button(right, text="✦  加入任务队列", style="Primary.TButton", command=self.generate)
        self.generate_button.pack(fill=X, ipady=7)
        self.review_button = ttk.Button(right, text="审核并保存待审作品", state="disabled", command=self.save_reviewed_results)
        self.review_button.pack(fill=X, pady=(8, 0))
        self.progress = ttk.Progressbar(right, mode="indeterminate")
        self.progress.pack(fill=X, pady=(8, 4))
        self.status = StringVar(value="就绪 · 首次创作会启动内置引擎。")
        ttk.Label(right, textvariable=self.status, style="Hint.TLabel", wraplength=370).pack(fill=X, pady=(0, 8))
        ttk.Label(right, text="任务队列 · 依次生成，失败项双击查看", style="Card.TLabel").pack(anchor="w")
        self.tasks = ttk.Treeview(right, columns=("mode", "state"), show="headings", height=5)
        self.tasks.heading("mode", text="任务 / 工作流")
        self.tasks.heading("state", text="状态")
        self.tasks.column("mode", width=258)
        self.tasks.column("state", width=100, anchor="center")
        self.tasks.tag_configure("failed", foreground="#ff9a9a")
        self.tasks.pack(fill=X, pady=(5, 8))
        self.tasks.bind("<Double-1>", self.show_task_error)
        self.results = ttk.Treeview(right, columns=("file",), show="headings", height=2)
        self.results.heading("file", text="已保存作品 · 双击打开")
        self.results.column("file", width=340)
        self.results.pack(fill=X)
        self.results.bind("<Double-1>", self.open_result)
        ttk.Button(right, text="打开输出目录", command=self.open_output).pack(fill=X, pady=(8, 0))

        self.nav_buttons[self.active_flow].configure(style="NavActive.TButton")
        self.render_form()
        threading.Thread(target=self.queue_worker, daemon=True).start()
        self.root.after(120, self.drain_events)

    def scroll_form(self, event):
        pointer = self.root.winfo_containing(event.x_root, event.y_root)
        if pointer and (pointer == self.canvas or str(pointer).startswith(str(self.form))):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def choose_output(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get(), title="选择生成结果保存目录")
        if selected:
            self.output_var.set(selected)

    def choose_image(self, key):
        selected = filedialog.askopenfilename(title="选择参考图片", filetypes=[
            ("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("所有文件", "*.*")])
        if selected:
            self.vars[key].set(selected)

    def drop_image(self, key, event):
        paths = [Path(path) for path in self.root.tk.splitlist(event.data)]
        if not paths or any(not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES for path in paths):
            messagebox.showerror("图片无效", "请拖入本机的 PNG、JPG、WEBP、BMP 或 TIFF 图片。", parent=self.root)
            return
        if self.active_flow == "qwen_edit" and key.startswith("image_"):
            start = int(key.rsplit("_", 1)[1])
            if start + len(paths) > 7:
                messagebox.showerror("图片过多", "多参考图编辑最多支持 6 张图片。", parent=self.root)
                return
            try:
                count = int(self.vars["reference_count"].get())
            except ValueError:
                count = 1
            self.vars["reference_count"].set(str(max(count, start + len(paths) - 1)))
            for index, path in enumerate(paths, start):
                self.vars[f"image_{index}"].set(str(path))
        elif len(paths) == 1:
            self.vars[key].set(str(paths[0]))
            if key == "source_image":
                self.vars["cutout_mode"].set(True)
        else:
            messagebox.showerror("图片过多", "这个栏位只能放入一张图片。", parent=self.root)

    def save_form(self):
        current = {}
        for key, widget in self.widgets.items():
            current[key] = widget.get("1.0", "end-1c") if isinstance(widget, Text) else self.vars[key].get()
        self.values[self.active_flow] = current

    def change_flow(self, _event=None):
        chosen = next(flow for flow, item in WORKFLOWS.items() if item["name"] == self.flow_label.get())
        self.set_flow(chosen)

    def set_flow(self, chosen):
        if chosen == self.active_flow:
            return
        self.save_form()
        self.nav_buttons[self.active_flow].configure(style="Nav.TButton")
        self.active_flow = chosen
        self.nav_buttons[chosen].configure(style="NavActive.TButton")
        self.flow_label.set(WORKFLOWS[chosen]["name"])
        self.flow_title.set(WORKFLOWS[chosen]["name"])
        self.flow_desc.set(FLOW_DESCRIPTIONS[chosen])
        self.render_form()
        self.canvas.yview_moveto(0)

    def render_form(self):
        for child in self.form.winfo_children():
            child.destroy()
        self.vars, self.widgets, self.file_buttons = {}, {}, {}
        fields = WORKFLOWS[self.active_flow]["fields"]
        self.fields = {item["key"]: item for item in fields}
        saved = self.values[self.active_flow]
        for group in GROUPS:
            group_fields = [item for item in fields if item["group"] == group]
            if not group_fields:
                continue
            section = ttk.LabelFrame(self.form, text=group, padding=12)
            section.pack(fill=X, pady=(0, 10), padx=(0, 5))
            for item in group_fields:
                key, kind = item["key"], item["kind"]
                row = ttk.Frame(section, style="Card.TFrame")
                row.pack(fill=X, pady=(2, 9))
                if kind == "bool":
                    var = BooleanVar(value=bool(saved[key]))
                    widget = ttk.Checkbutton(row, text=item["label"], variable=var)
                    widget.pack(anchor="w")
                else:
                    ttk.Label(row, text=item["label"], style="Card.TLabel",
                              font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
                    if kind == "text":
                        widget = Text(row, height=4, wrap="word", font=("Microsoft YaHei UI", 10),
                                      background=INPUT, foreground=TEXT, insertbackground=TEXT,
                                      relief="flat", padx=9, pady=7, selectbackground="#5a68a3")
                        widget.insert("1.0", str(saved[key]))
                        widget.pack(fill=X, pady=(3, 2))
                    else:
                        var = StringVar(value=str(saved[key]))
                        if kind == "choice":
                            choices = self.choices[WORKFLOWS[self.active_flow]["family"]].get(key, item["choices"])
                            widget = ttk.Combobox(row, textvariable=var, values=choices)
                        elif kind == "file":
                            picker = ttk.Frame(row, style="Card.TFrame")
                            picker.pack(fill=X, pady=(3, 2))
                            widget = ttk.Entry(picker, textvariable=var)
                            widget.pack(side=LEFT, fill=X, expand=True)
                            for target in (picker, widget):
                                target.drop_target_register(DND_FILES)
                                target.dnd_bind("<<Drop>>", lambda event, k=key: self.drop_image(k, event))
                            button = ttk.Button(picker, text="选择…", command=lambda k=key: self.choose_image(k))
                            button.pack(side=RIGHT, padx=(6, 0))
                            self.file_buttons[key] = button
                        else:
                            widget = ttk.Entry(row, textvariable=var)
                        if kind != "file":
                            widget.pack(fill=X, pady=(3, 2))
                self.widgets[key] = widget
                if kind != "text":
                    self.vars[key] = var
                hint = item["hint"] + (" 可从文件管理器拖入图片。" if kind == "file" else "")
                ttk.Label(row, text=hint, style="Hint.TLabel", wraplength=610,
                          justify="left").pack(anchor="w")
        self.size_note = None
        if self.active_flow in {"qwen", "qwen_edit", "qwen_alpha"}:
            self.size_note = ttk.Label(self.form, foreground=TEAL)
            self.size_note.pack(anchor="w", padx=12, pady=(0, 8))
        for key in ("manual_size", "aspect_ratio", "megapixels", "multiple", "width", "height", "format",
                    "save_mode", "random_seed", "reference_count", "cutout_mode"):
            if key in self.vars:
                self.vars[key].trace_add("write", lambda *_: self.refresh_controls())
        self.refresh_controls()

    def refresh_controls(self):
        if not self.widgets:
            return
        self.widgets["seed"].configure(state="disabled" if self.vars["random_seed"].get() else "normal")
        if self.active_flow == "qwen_edit":
            try:
                count = int(self.vars["reference_count"].get())
            except ValueError:
                count = 1
            for i in range(2, 7):
                state = "normal" if i <= count else "disabled"
                self.widgets[f"image_{i}"].configure(state=state)
                self.file_buttons[f"image_{i}"].configure(state=state)
            manual = self.vars["manual_size"].get()
            for key in ("width", "height"):
                self.widgets[key].configure(state="normal" if manual else "disabled")
            self.size_note.configure(text="画布使用手动宽高" if manual else "画布尺寸跟随参考图 1")
        elif self.active_flow == "qwen_alpha":
            cutout = self.vars["cutout_mode"].get()
            self.widgets["source_image"].configure(state="normal" if cutout else "disabled")
            self.file_buttons["source_image"].configure(state="normal" if cutout else "disabled")
            for key in ("manual_size", "aspect_ratio", "megapixels", "multiple", "width", "height"):
                self.widgets[key].configure(state="disabled" if cutout else "normal")
            if cutout:
                self.size_note.configure(text="抠图模式：画布尺寸跟随上传的原图")
        if self.active_flow not in {"qwen", "qwen_edit", "qwen_alpha"}:
            return
        if self.active_flow in {"qwen", "qwen_alpha"} and not (self.active_flow == "qwen_alpha" and self.vars["cutout_mode"].get()):
            manual = self.vars["manual_size"].get()
            for key in ("width", "height"):
                self.widgets[key].configure(state="normal" if manual else "disabled")
            for key in ("aspect_ratio", "megapixels", "multiple"):
                self.widgets[key].configure(state="disabled" if manual else "normal")
            try:
                if manual:
                    width, height = int(self.vars["width"].get()), int(self.vars["height"].get())
                else:
                    width, height = qwen_size({"manual_size": False,
                        "aspect_ratio": self.vars["aspect_ratio"].get(),
                        "megapixels": float(self.vars["megapixels"].get()),
                        "multiple": int(self.vars["multiple"].get())})
                self.size_note.configure(text=f"本次画面尺寸：{width} × {height} 像素")
            except (ValueError, KeyError, ZeroDivisionError):
                self.size_note.configure(text="画面尺寸：请检查数值")
        if "format" not in self.vars:
            return
        fmt = self.vars["format"].get()
        depths = {"png": ("8-bit", "16-bit"), "exr": ("32-bit float",),
                  "avif": ("auto", "8-bit YUV420", "10-bit YUV420")}.get(fmt, ())
        colors = {"png": ("sRGB",), "exr": ("sRGB", "HDR", "linear"),
                  "avif": ("sRGB", "HDR", "HDR PQ")}.get(fmt, ())
        for key, choices in (("bit_depth", depths), ("input_color_space", colors)):
            self.widgets[key].configure(values=choices)
            if self.vars[key].get() not in choices and choices:
                self.vars[key].set(choices[0])
        for key in ("crf", "save_mode"):
            self.widgets[key].configure(state="normal" if fmt == "avif" else "disabled")
        animated = fmt == "avif" and self.vars["save_mode"].get() == "animated"
        for key in ("fps", "loop_count"):
            self.widgets[key].configure(state="normal" if animated else "disabled")

    def run_worker(self, target):
        if self.busy:
            return
        self.busy = True
        self.generate_button.configure(state="disabled")
        self.progress.start(12)
        threading.Thread(target=self.worker_wrapper, args=(target,), daemon=True).start()

    def worker_wrapper(self, target):
        try:
            target()
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("done", None))

    def connect(self):
        def worker():
            server = self.ensure_server()
            self.events.put(("status", "离线引擎已启动，正在读取模型…"))
            self.events.put(("choices", options_from_server(server)))
            self.events.put(("status", "离线引擎已就绪，可以开始创作。"))
        self.run_worker(worker)

    def ensure_server(self):
        if self.server_process and self.server_process.poll() is None and self.server_url:
            try:
                request_json(self.server_url + "/system_stats", timeout=3)
                return self.server_url
            except (RuntimeError, urllib.error.URLError, TimeoutError, OSError):
                pass
        comfy = DEFAULT_COMFY
        python = comfy.parent / "python" / "python.exe"
        if not (comfy / "main.py").is_file() or not python.is_file():
            raise FileNotFoundError("内置推理环境不完整，请重新安装离线版")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("user", "input", "output", "temp"):
            (DATA_DIR / name).mkdir(exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = f"http://127.0.0.1:{port}"
        self.server_url = server
        self.events.put(("status", "正在启动内置离线引擎，首次加载可能需要几分钟…"))
        log_path = DATA_DIR / "engine.log"
        self.server_log = open(log_path, "ab")
        self.server_process = subprocess.Popen(
            [str(python), str(comfy / "main.py"), "--disable-auto-launch", "--listen", "127.0.0.1", "--port", str(port),
             "--disable-api-nodes", "--lowvram", "--disable-comfy-compiler", "--disable-all-custom-nodes", "--whitelist-custom-nodes", "ComfyUI-GGUF",
             "--user-directory", str(DATA_DIR / "user"), "--input-directory", str(DATA_DIR / "input"),
             "--output-directory", str(DATA_DIR / "output"), "--temp-directory", str(DATA_DIR / "temp")],
            cwd=str(comfy), stdin=subprocess.DEVNULL, stdout=self.server_log,
            stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(180):
            if self.server_process.poll() is not None:
                raise RuntimeError(f"ComfyUI 启动失败，请查看日志：{log_path}")
            try:
                request_json(server + "/system_stats", timeout=2)
                return server
            except (RuntimeError, urllib.error.URLError, TimeoutError, OSError):
                time.sleep(1)
        raise TimeoutError(f"ComfyUI 在 3 分钟内没有响应，请查看日志：{log_path}")

    def generate(self):
        self.save_form()
        flow = self.active_flow
        try:
            params = coerce(flow, self.values[flow])
            output_text = self.output_var.get().strip()
            if not output_text:
                raise ValueError("请选择输出目录")
            output = Path(output_text).expanduser()
        except ValueError as exc:
            messagebox.showerror("参数需要调整", str(exc), parent=self.root)
            return
        job_id = f"job-{self.next_job_id}"
        self.next_job_id += 1
        self.tasks.insert("", "end", iid=job_id,
                          values=(f"#{self.next_job_id - 1} {WORKFLOWS[flow]['name']}", "排队中"))
        self.pending_jobs += 1
        self.connect_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set(f"已加入任务队列；还有 {self.pending_jobs} 项待完成。")
        self.task_queue.put((job_id, flow, params, output))

    def queue_worker(self):
        while True:
            job_id, flow, params, output = self.task_queue.get()
            self.events.put(("task_state", (job_id, "运行中")))
            try:
                needs_review = self.execute_job(job_id, flow, params, output)
            except Exception as exc:
                self.events.put(("task_error", (job_id, str(exc))))
            else:
                self.events.put(("task_state", (job_id, "待审核" if needs_review else "完成")))
            finally:
                self.events.put(("task_finished", job_id))
                self.task_queue.task_done()

    def execute_job(self, job_id, flow, params, output):
        server = self.ensure_server()
        submitted = dict(params)
        for key in image_fields(flow, params):
            self.events.put(("status", f"正在上传 {Path(params[key]).name}…"))
            submitted[key] = upload_image(server, params[key])
        graph = build_prompt(flow, submitted)
        if flow == "qwen_edit" and not params["manual_size"]:
            with Image.open(params["image_1"]) as original:
                width, height = ImageOps.exif_transpose(original).size
            match_reference_size(graph, width, height)
        self.events.put(("status", f"正在提交 {WORKFLOWS[flow]['name']}，种子 {params['seed']}…"))
        result = request_json(server + "/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())}, timeout=30)
        if "prompt_id" not in result:
            raise RuntimeError(f"工作流未被接受：{str(result)[:1400]}")
        prompt_id = result["prompt_id"]
        self.events.put(("status", f"已提交任务 {prompt_id[:8]}，等待 ComfyUI 完成…"))
        for _ in range(2400):
            history = request_json(f"{server}/history/{prompt_id}", timeout=20).get(prompt_id)
            if history:
                break
            time.sleep(1.5)
        else:
            raise TimeoutError("任务等待超过一小时；请检查 ComfyUI 的队列和日志")
        status = history.get("status", {})
        if status.get("status_str") == "error" or not status.get("completed", False):
            messages = status.get("messages", [])
            latest = messages[-1] if messages else status
            details = latest[1] if isinstance(latest, (list, tuple)) and len(latest) > 1 else latest
            reason = str(details.get("exception_message") or details) if isinstance(details, dict) else str(details)
            if "aimdo memory compile error" in reason.lower():
                reason += "\n请退出并重启应用，然后降低画布尺寸。"
            raise RuntimeError(f"ComfyUI 执行失败：{reason[:800]}\n运行日志：{DATA_DIR / 'engine.log'}")
        images = [image for node in history.get("outputs", {}).values() for image in node.get("images", [])]
        if not images:
            raise RuntimeError("ComfyUI 已完成任务，但历史记录中没有图片输出")
        needs_review = flow.startswith("krea")
        if not needs_review:
            output.mkdir(parents=True, exist_ok=True)
        saved = []
        for image in images:
            query = urllib.parse.urlencode({"filename": image["filename"],
                "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
            with urllib.request.urlopen(f"{server}/view?{query}", timeout=60) as response:
                data = response.read()
            safe_name = Path(image["filename"]).name
            destination = output / f"{flow}_{prompt_id[:8]}_{safe_name}"
            if needs_review:
                self.events.put(("review_result", (job_id, destination, data)))
            else:
                destination.write_bytes(data)
                saved.append(destination)
                self.events.put(("result", (job_id, destination, data)))
        note = "生成完成：请查看预览，人工审核后点击保存。" if needs_review else f"完成：已保存 {len(saved)} 张到 {output}"
        self.events.put(("status", note))
        return needs_review

    def save_reviewed_results(self):
        if not self.pending_review:
            return
        if not messagebox.askyesno("人工审核", "请确认已查看作品，内容符合 Krea 许可与适用法律，再保存或分享。", parent=self.root):
            return
        for job_id, path, data in self.pending_review:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.result_paths.append(path)
            self.results.insert("", "end", values=(str(path),))
            self.tasks.set(job_id, "state", "完成")
        count = len(self.pending_review)
        self.pending_review.clear()
        self.review_button.configure(state="disabled")
        self.status.set(f"已审核并保存 {count} 张作品。")

    def drain_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    self.status.set(payload)
                elif event == "choices":
                    self.choices = payload
                    self.save_form()
                    self.render_form()
                elif event in {"result", "review_result"}:
                    job_id, path, data = payload
                    if event == "review_result":
                        self.pending_review.append((job_id, path, data))
                        self.review_button.configure(state="normal")
                    else:
                        self.result_paths.append(path)
                        self.results.insert("", "end", values=(str(path),))
                    try:
                        image = Image.open(io.BytesIO(data))
                        image.thumbnail((360, 350))
                        if "A" in image.getbands():
                            backdrop = Image.new("RGBA", image.size, "#eeeeee")
                            draw = ImageDraw.Draw(backdrop)
                            for y in range(0, image.height, 24):
                                for x in range(0, image.width, 24):
                                    if (x // 24 + y // 24) % 2:
                                        draw.rectangle((x, y, x + 23, y + 23), fill="#cccccc")
                            image = Image.alpha_composite(backdrop, image.convert("RGBA"))
                        self.preview_photo = ImageTk.PhotoImage(image.convert("RGB"))
                        self.preview.configure(image=self.preview_photo, text="")
                    except (OSError, ValueError):
                        self.preview.configure(image="", text=f"文件已保存：{path.name}\n此格式不能在窗口中预览")
                elif event == "error":
                    self.status.set("失败：" + payload)
                    messagebox.showerror("生图失败", payload, parent=self.root)
                elif event == "task_state":
                    job_id, state = payload
                    self.tasks.set(job_id, "state", state)
                elif event == "task_error":
                    job_id, reason = payload
                    self.tasks.set(job_id, "state", "失败")
                    self.tasks.item(job_id, tags=("failed",))
                    self.task_errors[job_id] = reason
                    self.status.set(f"任务 {job_id} 失败；双击队列条目查看原因。")
                elif event == "task_finished":
                    self.pending_jobs -= 1
                    if not self.pending_jobs:
                        self.progress.stop()
                        self.connect_button.configure(state="normal")
                elif event == "done":
                    self.busy = False
                    self.generate_button.configure(state="normal")
                    self.progress.stop()
        except queue.Empty:
            pass
        self.root.after(120, self.drain_events)

    def open_result(self, _event=None):
        selected = self.results.selection()
        if selected:
            os.startfile(self.results.item(selected[0], "values")[0])

    def show_task_error(self, _event=None):
        selected = self.tasks.selection()
        if selected and selected[0] in self.task_errors:
            messagebox.showerror("任务失败原因", self.task_errors[selected[0]], parent=self.root)

    def open_output(self):
        path = Path(self.output_var.get()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def close(self):
        if (self.busy or self.pending_jobs) and not messagebox.askyesno(
                "任务仍在运行", "任务队列尚未完成。退出会取消未完成任务并停止内置引擎，确定退出吗？", parent=self.root):
            return
        if self.pending_review and not messagebox.askyesno("作品尚未保存", "有 Krea 作品待审核。退出后不会复制到作品目录，确定退出吗？", parent=self.root):
            return
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
        if self.server_log:
            self.server_log.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sample = defaults("qwen_edit")
        sample["image_1"] = "uploaded.png"
        graph = build_prompt("qwen_edit", sample)
        match_reference_size(graph, 503, 707)
        assert graph["490"]["inputs"]["width"] == 503
        assert graph["461"]["inputs"]["images"] == ["490", 0]
        sample["format"], sample["bit_depth"] = "avif", "auto"
        graph = build_prompt("qwen_edit", sample)
        match_reference_size(graph, 503, 707)
        assert graph["460"]["inputs"]["image"] == ["490", 0]
        dummy = App.__new__(App)
        dummy.task_queue, dummy.events = queue.Queue(), queue.Queue()
        seen = []
        def record(job_id, *_):
            seen.append(job_id)
            if job_id == "job-1":
                raise RuntimeError("预期的任务失败")
            return False
        dummy.execute_job = record
        threading.Thread(target=dummy.queue_worker, daemon=True).start()
        for job_id in ("job-1", "job-2"):
            dummy.task_queue.put((job_id, "qwen", {}, Path(".")))
        dummy.task_queue.join()
        assert seen == ["job-1", "job-2"]
        assert any(event == "task_error" for event, _ in list(dummy.events.queue))
        app = App()
        app.root.withdraw()
        assert app.output_var.get() == str(DEFAULT_OUTPUT)
        app.set_flow("qwen_edit")
        assert not app.vars["manual_size"].get()
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("first image.png", "second image.png")]
            for path in paths:
                Image.new("RGB", (32, 32)).save(path)
            event = type("DropEvent", (), {"data": " ".join(f"{{{path}}}" for path in paths)})()
            app.drop_image("image_1", event)
            assert app.vars["reference_count"].get() == "2"
            assert [app.vars[f"image_{i}"].get() for i in (1, 2)] == list(map(str, paths))
        submitted = []
        def fake_job(job_id, flow, params, output):
            submitted.append((job_id, flow, params["prompt"], output))
            return False
        app.execute_job = fake_job
        for flow, prompt in (("qwen", "第一个任务"), ("krea", "第二个任务")):
            app.set_flow(flow)
            app.widgets["prompt"].insert("1.0", prompt)
            app.generate()
        app.task_queue.join()
        app.drain_events()
        assert [item[1:3] for item in submitted] == [("qwen", "第一个任务"), ("krea", "第二个任务")]
        assert app.pending_jobs == 0 and app.tasks.set("job-2", "state") == "完成"
        app.root.destroy()
        if sys.stdout:
            print("app checks passed")
    else:
        App().run()
