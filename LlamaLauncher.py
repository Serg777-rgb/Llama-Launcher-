#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой Запускатор для локальных LLM (llama-server)
Никаких консолей и ручного ввода команд — только кнопки и ползунки.

Как собрать в portable .exe (делается на Windows):
    1) pip install pyinstaller
    2) pyinstaller --onefile --windowed --name "LlamaLauncher" LlamaLauncher.py
    3) Готовый файл будет в папке dist\\LlamaLauncher.exe
"""

import json
import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "launcher_config.json")


def detect_system():
    """Определяем ядра CPU и объём RAM, без сторонних библиотек."""
    cpu_count = os.cpu_count() or 4
    ram_gb = None
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            ram_gb = round(stat.ullTotalPhys / (1024 ** 3))
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        ram_gb = round(kb / (1024 ** 2))
                        break
    except Exception:
        ram_gb = None
    return cpu_count, ram_gb


DETECTED_CORES, DETECTED_RAM_GB = detect_system()

# ---------- Поиск установленных браузеров (для автозапуска в нужном) ----------
BROWSER_CANDIDATES = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
}

BROWSER_LABELS = {
    "default": "Браузер по умолчанию",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "firefox": "Firefox",
    "custom": "Другой (указать вручную)",
    "none": "Не открывать автоматически",
}


def find_browser_path(key):
    for path in BROWSER_CANDIDATES.get(key, []):
        if path and os.path.exists(path):
            return path
    return None

# Разумные значения по умолчанию исходя из обнаруженного железа
_DEFAULT_THREADS = max(1, DETECTED_CORES - 1) if DETECTED_CORES else 4
if DETECTED_RAM_GB and DETECTED_RAM_GB >= 32:
    _DEFAULT_CONTEXT = 16384
elif DETECTED_RAM_GB and DETECTED_RAM_GB >= 16:
    _DEFAULT_CONTEXT = 8192
else:
    _DEFAULT_CONTEXT = 4096

DEFAULT_CONFIG = {
    "server_path": "",
    "model_path": "",
    "threads": _DEFAULT_THREADS,
    "context": _DEFAULT_CONTEXT,
    "ngl": 0,
    "batch": 2048,
    "ubatch": 512,
    "port": 8080,
    "mlock": True,
    "flash_attn": True,
    "cache_quant": True,
    "temp": 0.8,
    "top_p": 0.9,
    "min_p": 0.05,
    "repeat_penalty": 1.15,
    "browser_choice": "default",
    "browser_custom_path": "",
}

# ---------- Подсказки для каждого параметра (текст всплывающей шпаргалки) ----------
TOOLTIPS = {
    "server_path": "Программа, которая умеет запускать нейросети (файл llama-server.exe "
                    "из архива llama.cpp). Один раз выбрал — она запомнится.",
    "model_path": "Сама нейросеть-\"мозг\" в виде файла .gguf. Обычно весит несколько "
                  "гигабайт. Чем файл больше — тем модель \"умнее\", но медленнее.",
    "threads": "Сколько ядер процессора одновременно думают над ответом, по числу физических ядер процессора\n"
               f"Автоматически может выставить потоки !!ПРОВЕРЬТЕ ВЫБОР ЯДРА ИЛИ ПОТОКИ!! (обнаружено ядер: {DETECTED_CORES}).\n"
               "Больше — быстрее, но не всегда. При использовании видеокарты можно уменьшить",
    "context": "Сколько текста ИИ \"помнит\" одновременно — вся переписка плюс твоё "
               "сообщение. Чем больше — тем больше нужно оперативной памяти.",
    "ngl": "Сколько частей нейросети посчитает видеокарта вместо процессора.\n"
           "Если видеокарты нет, или она старая/слабая — оставляйте 0, "
           "пусть всё считает процессор.",
    "batch": "Сколько текста процессор \"проглатывает\" за один присест, пока читает "
             "твоё сообщение (не влияет на сам ответ, только на скорость чтения).",
    "ubatch": "Технический родственник параметра выше — на сколько частей дробится "
              "чтение сообщения. Обычно можно не трогать.",
    "port": "Номер \"двери\", через которую браузер общается с программой. "
            "Если не уверен — оставь как есть (8080).",
    "mlock": "Не даёт Windows выгружать нейросеть из оперативной памяти на диск. "
             "Без этой галочки скорость может внезапно проседать.",
    "flash_attn": "Специальный ускоритель, который считает быстрее и экономит память. "
                  "Практически всегда стоит держать включённым (программа сама "
                  "передаст нужное значение серверу).",
    "cache_quant": "Сжимает \"память\" переписки, чтобы длинный диалог не съел всю "
                   "оперативную память компьютера.",
    "presets": "Выбери, каким должен быть ответ:\nточный — сухой и по фактам,\n"
               "обычный — золотая середина,\nтворческий — неожиданный и живой.",
    "browser_choice": "В каком браузере автоматически откроется чат с ИИ после запуска.\n"
                       "Удобно, если хочешь держать вкладки с ИИ отдельно от обычного "
                       "интернета — например, ИИ в Edge, а всё остальное в Chrome.",
}

PRESETS = {
    "🎯 Точный (код / факты)": {"temp": 0.15, "top_p": 0.8, "min_p": 0.1, "repeat_penalty": 1.1},
    "💬 Обычный (баланс)": {"temp": 0.8, "top_p": 0.9, "min_p": 0.05, "repeat_penalty": 1.15},
    "🎨 Творческий": {"temp": 1.1, "top_p": 0.95, "min_p": 0.02, "repeat_penalty": 1.1},
}


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class ToolTip:
    """Простая всплывающая подсказка при наведении мышкой на виджет."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.attributes("-topmost", True)
        except Exception:
            pass
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify="left", background="#ffffe0",
            relief="solid", borderwidth=1, font=("Segoe UI", 9),
            wraplength=340, padx=8, pady=6,
        )
        label.pack()

    def hide(self, _event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


def make_hint_label(parent, text, tooltip_key):
    """Ярлык параметра + маленький значок (?), у обоих есть подсказка при наведении."""
    frame = ttk.Frame(parent)
    ttk.Label(frame, text=text).pack(side="left")
    hint = ttk.Label(frame, text=" (?)", foreground="#1565c0", cursor="question_arrow")
    hint.pack(side="left")
    tip_text = TOOLTIPS.get(tooltip_key, "")
    ToolTip(frame, tip_text)
    ToolTip(hint, tip_text)
    return frame


class LlamaLauncherApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.process = None
        self.reader_thread = None

        root.title("Простой Запускатор ИИ")
        root.geometry("780x760")
        root.minsize(720, 680)

        self._build_ui()
        self._load_values_into_ui()

    # ---------- UI BUILD ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- Баннер с обнаруженным железом ---
        ram_text = f"{DETECTED_RAM_GB} ГБ" if DETECTED_RAM_GB else "не удалось определить"
        info = ttk.Label(
            self.root,
            text=f"🖥  Обнаружено: {DETECTED_CORES} ядер CPU, RAM: {ram_text} "
                 "— настройки ниже уже подобраны автоматически",
            foreground="#555",
        )
        info.pack(fill="x", padx=10, pady=(8, 0))

        # --- Файлы ---
        files_frame = ttk.LabelFrame(self.root, text="1. Файлы")
        files_frame.pack(fill="x", **pad)

        self.server_var = tk.StringVar()
        self.model_var = tk.StringVar()

        self._file_row(files_frame, "Программа llama-server:", self.server_var,
                        self._browse_server, 0, "server_path")
        self._file_row(files_frame, "Файл модели (.gguf):", self.model_var,
                        self._browse_model, 1, "model_path")

        # --- Пресеты поведения ---
        preset_frame = ttk.LabelFrame(self.root, text="2. Какой нужен ответ?")
        preset_frame.pack(fill="x", **pad)
        make_hint_label(preset_frame, "Наведи на кнопки, чтобы узнать разницу:", "presets").pack(
            anchor="w", padx=10, pady=(6, 0))
        btns = ttk.Frame(preset_frame)
        btns.pack(fill="x", padx=10, pady=8)
        preset_tips = {
            "🎯 Точный (код / факты)": "Ответы сухие, точные, без фантазии. "
                                        "Подходит для кода, цифр, фактов.",
            "💬 Обычный (баланс)": "Золотая середина — подходит для обычного общения.",
            "🎨 Творческий": "Ответы более живые и неожиданные, с фантазией. "
                             "Подходит для историй и творческих идей.",
        }
        for name in PRESETS:
            btn = ttk.Button(btns, text=name, command=lambda n=name: self._apply_preset(n))
            btn.pack(side="left", expand=True, fill="x", padx=4)
            ToolTip(btn, preset_tips.get(name, ""))

        # --- Основные параметры ---
        main_frame = ttk.LabelFrame(self.root, text="3. Настройки железа")
        main_frame.pack(fill="x", **pad)

        self.threads_var = tk.IntVar()
        self.context_var = tk.IntVar()
        self.ngl_var = tk.IntVar()
        self.batch_var = tk.IntVar()
        self.ubatch_var = tk.IntVar()
        self.port_var = tk.IntVar()

        self._slider_row(main_frame, "Потоки CPU (-t):", self.threads_var, 1, 32, 0,
                          tooltip_key="threads")
        self._slider_row(main_frame, "Контекст, токенов (-c):", self.context_var, 512, 131072, 1,
                          step=512, tooltip_key="context")
        self._slider_row(main_frame, "Слоёв на GPU (-ngl):", self.ngl_var, 0, 100, 2,
                          tooltip_key="ngl")
        self._slider_row(main_frame, "Batch (-b):", self.batch_var, 128, 4096, 3,
                          step=128, tooltip_key="batch")
        self._slider_row(main_frame, "Ubatch (-ub):", self.ubatch_var, 64, 2048, 4,
                          step=64, tooltip_key="ubatch")

        port_row = ttk.Frame(main_frame)
        port_row.grid(row=5, column=0, columnspan=3, sticky="w", padx=10, pady=4)
        make_hint_label(port_row, "Порт сервера:", "port").pack(side="left")
        ttk.Entry(port_row, textvariable=self.port_var, width=8).pack(side="left", padx=6)

        # --- Галочки ---
        check_frame = ttk.LabelFrame(self.root, text="4. Дополнительно")
        check_frame.pack(fill="x", **pad)
        self.mlock_var = tk.BooleanVar()
        self.fa_var = tk.BooleanVar()
        self.cache_quant_var = tk.BooleanVar()

        def check_row(text, var, tooltip_key):
            row = ttk.Frame(check_frame)
            row.pack(anchor="w", padx=10, pady=2, fill="x")
            cb = ttk.Checkbutton(row, text=text, variable=var)
            cb.pack(side="left")
            hint = ttk.Label(row, text=" (?)", foreground="#1565c0", cursor="question_arrow")
            hint.pack(side="left")
            tip = TOOLTIPS.get(tooltip_key, "")
            ToolTip(cb, tip)
            ToolTip(hint, tip)

        check_row("--mlock (не давать системе выгружать модель из RAM)",
                   self.mlock_var, "mlock")
        check_row("-fa Flash Attention (быстрее и экономнее по памяти)",
                   self.fa_var, "flash_attn")
        check_row("Сжимать память чата (--cache-type-k/v q8_0)",
                   self.cache_quant_var, "cache_quant")

        # --- Выбор браузера ---
        browser_row = ttk.Frame(check_frame)
        browser_row.pack(anchor="w", padx=10, pady=(8, 4), fill="x")
        make_hint_label(browser_row, "Открыть чат в браузере:", "browser_choice").pack(side="left")

        self.browser_choice_var = tk.StringVar()
        available_keys = ["default"] + [k for k in BROWSER_CANDIDATES if find_browser_path(k)] + ["custom", "none"]
        # без дублей, сохраняя порядок
        seen = set()
        available_keys = [k for k in available_keys if not (k in seen or seen.add(k))]
        self.browser_combo = ttk.Combobox(
            browser_row, state="readonly", width=28,
            values=[BROWSER_LABELS[k] for k in available_keys],
        )
        self.browser_combo.pack(side="left", padx=8)
        self._browser_keys_order = available_keys

        self.browser_custom_var = tk.StringVar()
        self.browser_custom_entry = ttk.Entry(browser_row, textvariable=self.browser_custom_var, width=32)
        self.browser_custom_btn = ttk.Button(browser_row, text="Обзор...", command=self._browse_browser)

        def on_browser_change(_event=None):
            key = self._current_browser_key()
            if key == "custom":
                self.browser_custom_entry.pack(side="left", padx=4)
                self.browser_custom_btn.pack(side="left", padx=4)
            else:
                self.browser_custom_entry.pack_forget()
                self.browser_custom_btn.pack_forget()

        self.browser_combo.bind("<<ComboboxSelected>>", on_browser_change)
        self._on_browser_change_hook = on_browser_change

        # --- Кнопки запуска ---
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=10, pady=10)
        self.start_btn = tk.Button(action_frame, text="▶  ЗАПУСТИТЬ", bg="#2e7d32", fg="white",
                                    font=("Segoe UI", 12, "bold"), height=2, command=self.start_server)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.stop_btn = tk.Button(action_frame, text="■  СТОП", bg="#c62828", fg="white",
                                   font=("Segoe UI", 12, "bold"), height=2, command=self.stop_server,
                                   state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=4)

        # --- Лог ---
        log_frame = ttk.LabelFrame(self.root, text="Журнал сервера")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(log_frame, height=10, bg="#111", fg="#0f0", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _file_row(self, parent, label, var, browse_cmd, row, tooltip_key):
        hint = make_hint_label(parent, label, tooltip_key)
        hint.grid(row=row, column=0, sticky="w", padx=10, pady=4)
        entry = ttk.Entry(parent, textvariable=var, width=60)
        entry.grid(row=row, column=1, sticky="we", padx=4, pady=4)
        ttk.Button(parent, text="Обзор...", command=browse_cmd).grid(row=row, column=2, padx=8)
        parent.columnconfigure(1, weight=1)

    def _slider_row(self, parent, label, var, frm, to, row, step=1, tooltip_key=None):
        hint = make_hint_label(parent, label, tooltip_key)
        hint.grid(row=row, column=0, sticky="w", padx=10, pady=4)
        scale = ttk.Scale(parent, from_=frm, to=to, orient="horizontal",
                           command=lambda v, var=var, step=step: var.set(round(float(v) / step) * step))
        scale.grid(row=row, column=1, sticky="we", padx=4, pady=4)
        value_label = ttk.Label(parent, width=8, anchor="e")
        value_label.grid(row=row, column=2, padx=8)

        def sync_label(*_):
            value_label.config(text=str(var.get()))
        var.trace_add("write", sync_label)

        # link scale <-> var initial
        def set_scale_from_var(*_):
            scale.set(var.get())
        var.trace_add("write", lambda *_: None)  # placeholder, value set on load
        parent.columnconfigure(1, weight=1)
        # store scale ref so we can set it after values load
        setattr(self, f"_scale_{id(var)}", scale)

    # ---------- ЗНАЧЕНИЯ ----------
    def _load_values_into_ui(self):
        c = self.cfg
        self.server_var.set(c["server_path"])
        self.model_var.set(c["model_path"])
        self.threads_var.set(c["threads"])
        self.context_var.set(c["context"])
        self.ngl_var.set(c["ngl"])
        self.batch_var.set(c["batch"])
        self.ubatch_var.set(c["ubatch"])
        self.port_var.set(c["port"])
        self.mlock_var.set(c["mlock"])
        self.fa_var.set(c["flash_attn"])
        self.cache_quant_var.set(c["cache_quant"])
        self.temp = c["temp"]
        self.top_p = c["top_p"]
        self.min_p = c["min_p"]
        self.repeat_penalty = c["repeat_penalty"]

        saved_key = c.get("browser_choice", "default")
        if saved_key not in self._browser_keys_order:
            saved_key = "default"
        idx = self._browser_keys_order.index(saved_key)
        self.browser_combo.current(idx)
        self.browser_custom_var.set(c.get("browser_custom_path", ""))
        self._on_browser_change_hook()

        # sync sliders visual position
        for var in [self.threads_var, self.context_var, self.ngl_var, self.batch_var, self.ubatch_var]:
            scale = getattr(self, f"_scale_{id(var)}", None)
            if scale is not None:
                scale.set(var.get())

    def _apply_preset(self, name):
        p = PRESETS[name]
        self.temp = p["temp"]
        self.top_p = p["top_p"]
        self.min_p = p["min_p"]
        self.repeat_penalty = p["repeat_penalty"]
        messagebox.showinfo("Пресет применён", f"Выбран режим: {name}")

    def _current_browser_key(self):
        idx = self.browser_combo.current()
        if idx < 0 or idx >= len(self._browser_keys_order):
            return "default"
        return self._browser_keys_order[idx]

    def _browse_browser(self):
        path = filedialog.askopenfilename(title="Выбери программу браузера",
                                           filetypes=[("Исполняемый файл", "*.exe"), ("Все файлы", "*.*")])
        if path:
            self.browser_custom_var.set(path)

    def _browse_server(self):
        path = filedialog.askopenfilename(title="Выбери llama-server",
                                           filetypes=[("Исполняемый файл", "*.exe"), ("Все файлы", "*.*")])
        if path:
            self.server_var.set(path)

    def _browse_model(self):
        path = filedialog.askopenfilename(title="Выбери модель",
                                           filetypes=[("GGUF модели", "*.gguf"), ("Все файлы", "*.*")])
        if path:
            self.model_var.set(path)

    def _collect_config(self):
        return {
            "server_path": self.server_var.get(),
            "model_path": self.model_var.get(),
            "threads": self.threads_var.get(),
            "context": self.context_var.get(),
            "ngl": self.ngl_var.get(),
            "batch": self.batch_var.get(),
            "ubatch": self.ubatch_var.get(),
            "port": self.port_var.get(),
            "mlock": self.mlock_var.get(),
            "flash_attn": self.fa_var.get(),
            "cache_quant": self.cache_quant_var.get(),
            "temp": self.temp,
            "top_p": self.top_p,
            "min_p": self.min_p,
            "repeat_penalty": self.repeat_penalty,
            "browser_choice": self._current_browser_key(),
            "browser_custom_path": self.browser_custom_var.get(),
        }

    def _build_command(self, cfg):
        cmd = [
            cfg["server_path"],
            "-m", cfg["model_path"],
            "-t", str(cfg["threads"]),
            "-c", str(cfg["context"]),
            "-ngl", str(cfg["ngl"]),
            "-b", str(cfg["batch"]),
            "-ub", str(cfg["ubatch"]),
            "--port", str(cfg["port"]),
            "--temp", str(cfg["temp"]),
            "--top-p", str(cfg["top_p"]),
            "--min-p", str(cfg["min_p"]),
            "--repeat-penalty", str(cfg["repeat_penalty"]),
        ]
        if cfg["mlock"]:
            cmd.append("--mlock")
        if cfg["flash_attn"]:
            cmd += ["-fa", "on"]
        if cfg["cache_quant"]:
            cmd += ["--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]
        return cmd

    # ---------- ЗАПУСК / ОСТАНОВКА ----------
    def start_server(self):
        cfg = self._collect_config()
        if not cfg["server_path"] or not os.path.exists(cfg["server_path"]):
            messagebox.showerror("Ошибка", "Не выбран (или не найден) файл llama-server.")
            return
        if not cfg["model_path"] or not os.path.exists(cfg["model_path"]):
            messagebox.showerror("Ошибка", "Не выбран (или не найден) файл модели.")
            return

        save_config(cfg)
        cmd = self._build_command(cfg)
        self._log("Запуск: " + " ".join(cmd) + "\n")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=os.path.dirname(cfg["server_path"]),
            )
        except Exception as e:
            messagebox.showerror("Не удалось запустить", str(e))
            return

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

        threading.Thread(
            target=self._open_browser_when_ready,
            args=(cfg["port"], cfg["browser_choice"], cfg["browser_custom_path"]),
            daemon=True,
        ).start()

    def _open_browser_when_ready(self, port, browser_choice, browser_custom_path):
        time.sleep(3)
        if not (self.process and self.process.poll() is None):
            return
        url = f"http://127.0.0.1:{port}"

        if browser_choice == "none":
            return

        if browser_choice == "default":
            webbrowser.open(url)
            return

        if browser_choice == "custom":
            exe_path = browser_custom_path
        else:
            exe_path = find_browser_path(browser_choice)

        if exe_path and os.path.exists(exe_path):
            try:
                subprocess.Popen([exe_path, url])
                return
            except Exception:
                pass
        # если что-то пошло не так — не оставляем пользователя без браузера вообще
        self._log(f"\n[Не удалось открыть выбранный браузер, открываю браузер по умолчанию]\n")
        webbrowser.open(url)

    def _read_output(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self._log(line)
        self._log("\n[Сервер остановлен]\n")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _log(self, text):
        def append():
            self.log_text.insert("end", text)
            self.log_text.see("end")
        self.root.after(0, append)

    def stop_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _on_close(self):
        self.stop_server()
        save_config(self._collect_config())
        self.root.destroy()


def main():
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    app = LlamaLauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
