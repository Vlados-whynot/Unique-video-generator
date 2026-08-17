import os
import re
import time
import uuid
import json
import random
import threading
import requests
import subprocess
from datetime import datetime, timezone
import PIL.Image
from PIL import ImageDraw, ImageFont
import customtkinter as ctk
from tkinter import filedialog, colorchooser, Menu, simpledialog

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

from playwright.sync_api import sync_playwright

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def add_clipboard_support(widget):
    def paste_event(event=None):
        try:
            clipboard = widget.clipboard_get()
            if isinstance(widget, ctk.CTkTextbox):
                widget.insert("insert", clipboard)
            elif isinstance(widget, ctk.CTkEntry):
                widget.insert("insert", clipboard)
        except Exception:
            pass
        return "break"

    widget.bind("<Control-Key-v>", paste_event)
    widget.bind("<Control-Key-V>", paste_event)
    widget.bind("<Command-Key-v>", paste_event)
    widget.bind("<Command-Key-V>", paste_event)

    menu = Menu(widget, tearoff=0)
    menu.add_command(label="Вставить", command=paste_event)

    def show_context_menu(event):
        menu.tk_popup(event.x_root, event.y_root)

    widget.bind("<Button-3>", show_context_menu)


def generate_unique_ffmpeg_params():
    devices = [
        ("Apple", "iPhone 15 Pro", "17.5.1"),
        ("Apple", "iPhone 14 Pro", "17.4.1"),
        ("Apple", "iPhone 13 Pro", "16.6"),
        ("Samsung", "Galaxy S23 Ultra", "Android 14")
    ]
    
    make, model, software = random.choice(devices)
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = [
        '-profile:v', 'high',
        '-level:v', '4.0',
        '-pix_fmt', 'yuv420p',
        '-color_primaries', 'bt709',
        '-color_trc', 'bt709',
        '-colorspace', 'bt709',
        '-movflags', '+use_metadata_tags+faststart',
        '-metadata', f'creation_time={current_time}',
        '-metadata', 'encoder=',
        '-metadata:s:v:0', 'encoder=',
        '-metadata:s:a:0', 'encoder=',
        '-metadata', 'handler_name=Core Media Video',
        '-metadata:s:v:0', 'handler_name=Core Media Video',
        '-metadata:s:a:0', 'handler_name=Core Media Audio',
        '-metadata', f'com.apple.quicktime.make={make}',
        '-metadata', f'com.apple.quicktime.model={model}',
        '-metadata', f'com.apple.quicktime.software={software}',
        '-metadata', f'make={make}',
        '-metadata', f'model={model}'
    ]
    return params


def get_video_dimensions(video_path):
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height',
        '-of', 'csv=s=x:p=0',
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        w, h = map(int, result.stdout.strip().split('x'))
        return w, h
    except Exception:
        return 1080, 1920


def extract_first_frame(video_path, preview_w=300, preview_h=533):
    temp_frame = f"temp_preview_{uuid.uuid4().hex[:6]}.jpg"
    cmd = [
        'ffmpeg', '-y',
        '-ss', '00:00:00',
        '-i', video_path,
        '-vframes', '1',
        '-q:v', '2',
        temp_frame
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        img = PIL.Image.open(temp_frame).resize((preview_w, preview_h))
        os.remove(temp_frame)
        return img
    except Exception:
        if os.path.exists(temp_frame):
            os.remove(temp_frame)
        return None


def draw_text_overlay(text: str, target_width: int, target_height: int, font_scale: float, y_position_pct: float, bg_color_hex: str, text_color_hex: str, font_path_or_name: str = "arial.ttf") -> PIL.Image.Image:
    lines = [line.strip() for line in text.split('\n')]
    
    img = PIL.Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
    if not any(lines):
        return img

    font_size = int(target_width * 0.05 * font_scale)
    try:
        font = ImageFont.truetype(font_path_or_name, font_size)
    except Exception:
        font = ImageFont.load_default()

    padding_x = int(font_size * 0.4)
    padding_y = int(font_size * 0.25)
    line_spacing = int(font_size * 0.3)
    radius = int(font_size * 0.3)

    draw = ImageDraw.Draw(img)
    current_y = int(target_height * (y_position_pct / 100.0))

    def hex_to_rgba(hex_str, alpha=240):
        hex_str = hex_str.lstrip('#')
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)

    bg_rgba = hex_to_rgba(bg_color_hex, 240)
    text_rgba = hex_to_rgba(text_color_hex, 255)

    for line in lines:
        if not line:
            current_y += font_size + (padding_y * 2) + line_spacing
            continue

        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        top_offset = bbox[1]

        x = (target_width - w) // 2
        box_left = x - padding_x
        box_top = current_y
        box_right = x + w + padding_x
        box_bottom = current_y + h + (padding_y * 2)

        draw.rounded_rectangle(
            [box_left, box_top, box_right, box_bottom],
            radius=radius,
            fill=bg_rgba
        )
        text_draw_y = box_top + padding_y - top_offset
        draw.text((x, text_draw_y), line, fill=text_rgba, font=font)
        
        current_y = box_bottom + line_spacing

    return img


def render_video_ffmpeg(bg_path, fg_video_path, text_overlay_path, audio_path, audio_vol, output_path, ffmpeg_params):
    width, height = get_video_dimensions(fg_video_path)
    if width % 2 != 0: width -= 1
    if height % 2 != 0: height -= 1

    inputs = [
        '-loop', '1', '-i', bg_path,
        '-i', fg_video_path
    ]
    
    filter_chains = []
    
    filter_chains.append(f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[bg_scaled]")
    filter_chains.append(f"[1:v]chromakey=0x00FF00:0.15:0.08,despill=type=green[fg_key]")
    filter_chains.append(f"[bg_scaled][fg_key]overlay=0:H-h:shortest=1[comp1]")

    last_v_out = "[comp1]"
    input_count = 2

    if text_overlay_path and os.path.exists(text_overlay_path):
        inputs.extend(['-i', text_overlay_path])
        filter_chains.append(f"{last_v_out}[{input_count}:v]overlay=0:0[comp2]")
        last_v_out = "[comp2]"
        input_count += 1

    audio_cmd = []
    if audio_path and os.path.exists(audio_path):
        inputs.extend(['-i', audio_path])
        audio_idx = input_count
        audio_cmd = [
            '-filter_complex', f"{';'.join(filter_chains)}",
            '-map', last_v_out,
            '-map', f'{audio_idx}:a',
            '-filter:a', f'volume={audio_vol}',
            '-shortest'
        ]
    else:
        audio_cmd = [
            '-filter_complex', f"{';'.join(filter_chains)}",
            '-map', last_v_out,
            '-map', '1:a?',
            '-filter:a', f'volume={audio_vol}',
            '-shortest'
        ]

    cmd = [
        'ffmpeg', '-y',
        *inputs,
        *audio_cmd,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-c:a', 'aac',
        *ffmpeg_params,
        output_path
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


class UniqueVideoGeneratorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Unique Video Generator (Auto AI Model Select)")
        self.geometry("1080x980")
        self.resizable(False, False)

        self.save_directory = os.getcwd()
        self.is_cancelled = False
        
        self.bg_color_hex = "#FFFFFF"
        self.text_color_hex = "#000000"
        self.custom_font_path = None
        self.gemini_api_key = ""
        self.pack_cards = []

        self.style_presets = {
            "Минимализм": {"bg": "#FFFFFF", "text": "#000000", "font": "Arial", "size": 1.0, "y": 15},
            "Неон": {"bg": "#000000", "text": "#00FF66", "font": "Impact", "size": 1.2, "y": 20},
            "Темный стиль": {"bg": "#1E1E1E", "text": "#F5F5F5", "font": "Trebuchet MS", "size": 1.0, "y": 15},
            "Яркий акцент": {"bg": "#FF1744", "text": "#FFFFFF", "font": "Impact", "size": 1.1, "y": 25}
        }

        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=15, pady=15)

        self.left_panel = ctk.CTkFrame(self.main_container, width=670)
        self.left_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.right_panel = ctk.CTkFrame(self.main_container, width=340)
        self.right_panel.pack(side="right", fill="both", padx=(10, 0))

        # --- ЗАГОЛОВОК И УПРАВЛЕНИЕ ПРОЕКТОМ ---
        self.project_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.project_frame.pack(fill="x", padx=15, pady=(5, 5))

        self.title_label = ctk.CTkLabel(self.project_frame, text="Генератор с AI и пресетами", font=ctk.CTkFont(size=18, weight="bold"))
        self.title_label.pack(side="left")

        self.save_proj_btn = ctk.CTkButton(self.project_frame, text="💾 Сохранить", width=100, command=self.save_project_json)
        self.save_proj_btn.pack(side="right", padx=(5, 0))

        self.load_proj_btn = ctk.CTkButton(self.project_frame, text="📂 Загрузить", width=100, command=self.load_project_json)
        self.load_proj_btn.pack(side="right")

        # Настройка Gemini API
        self.ai_config_frame = ctk.CTkFrame(self.left_panel)
        self.ai_config_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(self.ai_config_frame, text="Gemini API Key:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)
        self.api_key_entry = ctk.CTkEntry(self.ai_config_frame, placeholder_text="Вставьте ключ AI Studio...", show="*", width=320)
        self.api_key_entry.pack(side="left", padx=(0, 10))
        add_clipboard_support(self.api_key_entry)

        self.save_key_btn = ctk.CTkButton(self.ai_config_frame, text="Сохранить ключ", width=120, command=self.save_api_key)
        self.save_key_btn.pack(side="left")

        # --- УПРАВЛЕНИЕ ПАКАМИ ---
        self.pack_control_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.pack_control_frame.pack(fill="x", padx=15, pady=5)

        self.add_pack_btn = ctk.CTkButton(
            self.pack_control_frame, 
            text="+ Добавить пак", 
            fg_color="#2e7d32", 
            hover_color="#1b5e20",
            command=self.add_pack_card
        )
        self.add_pack_btn.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(self.pack_control_frame, text="Фонов на пак:").pack(side="left", padx=(0, 5))
        self.count_entry = ctk.CTkEntry(self.pack_control_frame, width=50)
        self.count_entry.pack(side="left")
        self.count_entry.insert(0, "7")
        add_clipboard_support(self.count_entry)

        self.scroll_packs_frame = ctk.CTkScrollableFrame(self.left_panel, width=610, height=270)
        self.scroll_packs_frame.pack(pady=5, padx=15, fill="both")

        # --- СТИЛИ И НАСТРОЙКИ ---
        self.style_frame = ctk.CTkFrame(self.left_panel)
        self.style_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(self.style_frame, text="Пресеты стилей:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.preset_menu = ctk.CTkOptionMenu(
            self.style_frame, 
            values=list(self.style_presets.keys()),
            command=self.apply_style_preset
        )
        self.preset_menu.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        self.save_preset_btn = ctk.CTkButton(self.style_frame, text="+ Сохранить стиль", width=130, command=self.save_custom_preset)
        self.save_preset_btn.grid(row=0, column=2, padx=5, pady=5)

        self.text_settings_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.text_settings_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(self.text_settings_frame, text="Размер текста:").grid(row=0, column=0, sticky="w")
        self.size_slider = ctk.CTkSlider(self.text_settings_frame, from_=0.5, to=2.0, number_of_steps=30, command=lambda v: self.update_preview())
        self.size_slider.set(1.0)
        self.size_slider.grid(row=0, column=1, padx=10)

        ctk.CTkLabel(self.text_settings_frame, text="Позиция Y:").grid(row=1, column=0, sticky="w")
        self.y_slider = ctk.CTkSlider(self.text_settings_frame, from_=5, to=80, number_of_steps=75, command=lambda v: self.update_preview())
        self.y_slider.set(15)
        self.y_slider.grid(row=1, column=1, padx=10)

        ctk.CTkLabel(self.text_settings_frame, text="Шрифт:").grid(row=2, column=0, sticky="w")
        self.font_option_menu = ctk.CTkOptionMenu(
            self.text_settings_frame, 
            values=["Arial", "Impact", "Trebuchet MS", "Georgia", "Courier New", "Свой шрифт..."],
            command=self.on_font_change
        )
        self.font_option_menu.grid(row=2, column=1, padx=10, sticky="w")

        self.color_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.color_frame.pack(fill="x", padx=15, pady=5)
        
        self.bg_color_btn = ctk.CTkButton(self.color_frame, text="Цвет плашки", width=120, command=self.choose_bg_color)
        self.bg_color_btn.pack(side="left", padx=(0, 10))

        self.text_color_btn = ctk.CTkButton(self.color_frame, text="Цвет текста", width=120, command=self.choose_text_color)
        self.text_color_btn.pack(side="left")

        # --- ПАПКА И СТАРТ ---
        self.folder_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.folder_frame.pack(pady=5, fill="x", padx=15)
        self.folder_entry = ctk.CTkEntry(self.folder_frame, width=450)
        self.folder_entry.pack(side="left", padx=(0, 10))
        self.folder_entry.insert(0, self.save_directory)
        add_clipboard_support(self.folder_entry)
        
        self.browse_btn = ctk.CTkButton(self.folder_frame, text="Папка сохранения", width=130, command=self.select_folder)
        self.browse_btn.pack(side="right")

        self.buttons_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.buttons_frame.pack(pady=8, fill="x", padx=15)
        self.start_btn = ctk.CTkButton(self.buttons_frame, text="Сгенерировать все паки", command=self.start_process_thread, height=35, width=430)
        self.start_btn.pack(side="left", padx=(0, 10))
        self.stop_btn = ctk.CTkButton(self.buttons_frame, text="Стоп", command=self.cancel_process, height=35, width=130, fg_color="#D32F2F", state="disabled")
        self.stop_btn.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(self.left_panel, width=610)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=3)
        self.log_textbox = ctk.CTkTextbox(self.left_panel, width=610, height=80)
        self.log_textbox.pack(pady=3)
        self.log_textbox.configure(state="disabled")

        # --- ПРАВАЯ ПАНЕЛЬ ПРЕВЬЮ ---
        self.preview_title = ctk.CTkLabel(self.right_panel, text="Превью Пака №1", font=ctk.CTkFont(size=16, weight="bold"))
        self.preview_title.pack(pady=(10, 5))

        self.preview_label = ctk.CTkLabel(self.right_panel, text="")
        self.preview_label.pack(expand=True, padx=10, pady=10)

        self.add_pack_card()
        self.after(500, self.update_preview)

    def save_api_key(self):
        key = self.api_key_entry.get().strip()
        if key:
            self.gemini_api_key = key
            self.log("✅ Gemini API Key сохранен!")

    def generate_ai_text_for_card(self, card_data):
        if not GEMINI_AVAILABLE:
            self.log("⚠️ Установите библиотеку: pip install google-generativeai")
            return

        key = self.api_key_entry.get().strip() or self.gemini_api_key
        if not key:
            self.log("⚠️ Введите Gemini API Key вверху программы!")
            return

        topic = simpledialog.askstring("AI Генератор", "Укажите тему или нишу (например: Успех, Психология, Юмор):")
        if not topic:
            return

        def _ai_thread():
            try:
                self.log(f"🤖 Запрос к Gemini AI по теме '{topic}'...")
                genai.configure(api_key=key)
                
                # Автоматически находим активную доступную модель у аккаунта
                active_model_name = None
                try:
                    for m in genai.list_models():
                        if 'generateContent' in m.supported_generation_methods:
                            if 'flash' in m.name:
                                active_model_name = m.name
                                break
                            elif not active_model_name:
                                active_model_name = m.name
                except Exception:
                    pass

                if not active_model_name:
                    active_model_name = 'models/gemini-1.5-flash'

                model = genai.GenerativeModel(active_model_name)

                prompt = (
                    f"Напиши одну короткую, цепляющую цитату или надпись для видео на тему: '{topic}'. "
                    "Сделай 2-3 короткие строки. Без кавычек, без хэштегов и эмодзи."
                )
                
                response = model.generate_content(prompt)
                ai_text = response.text.strip()

                def _update_ui():
                    card_data["text"].delete("1.0", "end")
                    card_data["text"].insert("1.0", ai_text)
                    self.update_preview()
                    self.log(f"✨ Текст сгенерирован через ({active_model_name})!")

                self.after(0, _update_ui)

            except Exception as e:
                err_msg = str(e)
                self.log(f"❌ Ошибка Gemini API: {err_msg}")
                if "403" in err_msg or "User location is not supported" in err_msg:
                    self.log("💡 Подсказка: Gemini API требует включенного VPN при отправке запроса.")

        threading.Thread(target=_ai_thread, daemon=True).start()

    def apply_style_preset(self, preset_name):
        if preset_name in self.style_presets:
            p = self.style_presets[preset_name]
            self.bg_color_hex = p["bg"]
            self.text_color_hex = p["text"]
            self.size_slider.set(p["size"])
            self.y_slider.set(p["y"])
            self.font_option_menu.set(p["font"])
            self.custom_font_path = None
            self.update_preview()
            self.log(f"🎨 Применен стиль: '{preset_name}'")

    def save_custom_preset(self):
        name = simpledialog.askstring("Новый пресет", "Введите название стиля:")
        if name:
            self.style_presets[name] = {
                "bg": self.bg_color_hex,
                "text": self.text_color_hex,
                "font": self.font_option_menu.get(),
                "size": self.size_slider.get(),
                "y": self.y_slider.get()
            }
            self.preset_menu.configure(values=list(self.style_presets.keys()))
            self.preset_menu.set(name)
            self.log(f"✅ Сохранен новый стиль: '{name}'")

    def save_project_json(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if not file_path:
            return

        project_data = {
            "gemini_api_key": self.api_key_entry.get().strip(),
            "per_pack_limit": self.count_entry.get(),
            "save_directory": self.folder_entry.get(),
            "bg_color_hex": self.bg_color_hex,
            "text_color_hex": self.text_color_hex,
            "font_size": self.size_slider.get(),
            "y_pos": self.y_slider.get(),
            "font_name": self.font_option_menu.get(),
            "custom_font_path": self.custom_font_path,
            "packs": []
        }

        for card in self.pack_cards:
            project_data["packs"].append({
                "query": card["query"].get().strip(),
                "video": card["video_var"].get().strip(),
                "audio": card["audio_var"].get().strip(),
                "volume": card["audio_vol"].get(),
                "text": card["text"].get("1.0", "end-1c")
            })

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(project_data, f, ensure_ascii=False, indent=4)

        self.log(f"💾 Проект сохранен: {os.path.basename(file_path)}")

    def load_project_json(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            key = data.get("gemini_api_key", "")
            if key:
                self.api_key_entry.delete(0, "end")
                self.api_key_entry.insert(0, key)
                self.gemini_api_key = key

            self.count_entry.delete(0, "end")
            self.count_entry.insert(0, data.get("per_pack_limit", "7"))

            if os.path.exists(data.get("save_directory", "")):
                self.save_directory = data["save_directory"]
                self.folder_entry.delete(0, "end")
                self.folder_entry.insert(0, self.save_directory)

            self.bg_color_hex = data.get("bg_color_hex", "#FFFFFF")
            self.text_color_hex = data.get("text_color_hex", "#000000")
            self.size_slider.set(data.get("font_size", 1.0))
            self.y_slider.set(data.get("y_pos", 15))
            self.font_option_menu.set(data.get("font_name", "Arial"))
            self.custom_font_path = data.get("custom_font_path")

            for card in list(self.pack_cards):
                card["frame"].destroy()
            self.pack_cards.clear()

            for pack_info in data.get("packs", []):
                self.add_pack_card()
                card = self.pack_cards[-1]
                
                card["query"].insert(0, pack_info.get("query", ""))
                
                v_path = pack_info.get("video", "")
                if os.path.exists(v_path):
                    card["video_var"].set(v_path)
                    f_name = os.path.basename(v_path)
                    short_name = f_name[:12] + "..." if len(f_name) > 12 else f_name
                    card["video_btn"].configure(text=short_name, fg_color="#2e7d32")

                a_path = pack_info.get("audio", "")
                if os.path.exists(a_path):
                    card["audio_var"].set(a_path)
                    a_name = os.path.basename(a_path)
                    short_a = a_name[:10] + "..." if len(a_name) > 10 else a_name
                    card["audio_btn"].configure(text=f"Аудио: {short_a}", fg_color="#1565C0")

                card["audio_vol"].set(pack_info.get("volume", 1.0))
                card["text"].insert("1.0", pack_info.get("text", ""))

            self.update_preview()
            self.log(f"📂 Проект успешно загружен: {os.path.basename(file_path)}")

        except Exception as e:
            self.log(f"❌ Ошибка загрузки проекта: {e}")

    def on_font_change(self, choice):
        if choice == "Свой шрифт...":
            font_path = filedialog.askopenfilename(filetypes=[("Font Files", "*.ttf *.otf")])
            if font_path:
                self.custom_font_path = font_path
                self.log(f"✅ Загружен шрифт: {os.path.basename(font_path)}")
            else:
                self.font_option_menu.set("Arial")
                self.custom_font_path = None
        else:
            self.custom_font_path = None
        self.update_preview()

    def get_current_font(self):
        if self.custom_font_path:
            return self.custom_font_path
        font_map = {
            "Arial": "arial.ttf",
            "Impact": "impact.ttf",
            "Trebuchet MS": "trebuc.ttf",
            "Georgia": "georgia.ttf",
            "Courier New": "cour.ttf"
        }
        return font_map.get(self.font_option_menu.get(), "arial.ttf")

    def add_pack_card(self):
        pack_frame = ctk.CTkFrame(self.scroll_packs_frame, fg_color="#2b2b2b")
        pack_frame.pack(fill="x", pady=6, padx=5)

        card_data = {"frame": pack_frame}

        header_frame = ctk.CTkFrame(pack_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=8, pady=(5, 0))

        title_lbl = ctk.CTkLabel(header_frame, text="Пак №...", font=ctk.CTkFont(weight="bold"))
        title_lbl.pack(side="left")
        card_data["title_lbl"] = title_lbl

        ai_btn = ctk.CTkButton(
            header_frame, text="✨ Текст через AI", width=120, height=22,
            fg_color="#6A1B9A", hover_color="#4A148C",
            command=lambda: self.generate_ai_text_for_card(card_data)
        )
        ai_btn.pack(side="right", padx=(5, 0))

        remove_btn = ctk.CTkButton(
            header_frame, text="✕ Удалить", width=70, height=22, 
            fg_color="#c62828", hover_color="#8e0000",
            command=lambda: self.remove_pack_card(card_data)
        )
        remove_btn.pack(side="right")

        inputs_frame = ctk.CTkFrame(pack_frame, fg_color="transparent")
        inputs_frame.pack(fill="x", padx=8, pady=5)

        query_entry = ctk.CTkEntry(inputs_frame, placeholder_text="Запрос в Pinterest...", width=260)
        query_entry.pack(side="left", padx=(0, 10))
        add_clipboard_support(query_entry)
        card_data["query"] = query_entry

        video_path_var = ctk.StringVar(value="")
        card_data["video_var"] = video_path_var

        video_btn = ctk.CTkButton(
            inputs_frame, text="Выбрать MP4", width=120, 
            command=lambda: self.select_single_video(card_data)
        )
        video_btn.pack(side="left")
        card_data["video_btn"] = video_btn

        audio_frame = ctk.CTkFrame(pack_frame, fg_color="transparent")
        audio_frame.pack(fill="x", padx=8, pady=(0, 5))

        audio_path_var = ctk.StringVar(value="")
        card_data["audio_var"] = audio_path_var

        audio_btn = ctk.CTkButton(
            audio_frame, text="Звук: из MP4", width=130, fg_color="#424242",
            command=lambda: self.select_audio_file(card_data)
        )
        audio_btn.pack(side="left", padx=(0, 10))
        card_data["audio_btn"] = audio_btn

        ctk.CTkLabel(audio_frame, text="Громкость аудио:").pack(side="left", padx=(0, 5))
        vol_slider = ctk.CTkSlider(audio_frame, from_=0.0, to=1.5, number_of_steps=30, width=120)
        vol_slider.set(1.0)
        vol_slider.pack(side="left")
        card_data["audio_vol"] = vol_slider

        text_textbox = ctk.CTkTextbox(pack_frame, width=560, height=50)
        text_textbox.pack(padx=8, pady=(0, 8))
        text_textbox.bind("<KeyRelease>", lambda e: self.update_preview())
        add_clipboard_support(text_textbox)
        card_data["text"] = text_textbox

        self.pack_cards.append(card_data)
        self.renumber_packs()
        self.update_preview()

    def remove_pack_card(self, card_data):
        if len(self.pack_cards) <= 1:
            self.log("⚠️ Нельзя удалить последний оставшийся пак!")
            return
        
        card_data["frame"].destroy()
        self.pack_cards.remove(card_data)
        self.renumber_packs()
        self.update_preview()

    def renumber_packs(self):
        for idx, card in enumerate(self.pack_cards, 1):
            card["title_lbl"].configure(text=f"Пак №{idx}")

    def select_single_video(self, card_data):
        file_path = filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")])
        if file_path:
            card_data["video_var"].set(file_path)
            file_name = os.path.basename(file_path)
            short_name = file_name[:12] + "..." if len(file_name) > 12 else file_name
            card_data["video_btn"].configure(text=short_name, fg_color="#2e7d32")
            
            pack_num = self.pack_cards.index(card_data) + 1
            self.log(f"✅ Для Пак №{pack_num} выбрано видео: {file_name}")
            self.update_preview()

    def select_audio_file(self, card_data):
        file_path = filedialog.askopenfilename(filetypes=[("Audio files", "*.mp3 *.wav *.m4a")])
        if file_path:
            card_data["audio_var"].set(file_path)
            file_name = os.path.basename(file_path)
            short_name = file_name[:10] + "..." if len(file_name) > 10 else file_name
            card_data["audio_btn"].configure(text=f"Аудио: {short_name}", fg_color="#1565C0")
        else:
            card_data["audio_var"].set("")
            card_data["audio_btn"].configure(text="Звук: из MP4", fg_color="#424242")

    def select_folder(self):
        chosen_dir = filedialog.askdirectory(initialdir=self.save_directory)
        if chosen_dir:
            self.save_directory = chosen_dir
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, self.save_directory)

    def choose_bg_color(self):
        color = colorchooser.askcolor(title="Выберите цвет плашки")[1]
        if color:
            self.bg_color_hex = color
            self.update_preview()

    def choose_text_color(self):
        color = colorchooser.askcolor(title="Выберите цвет текста")[1]
        if color:
            self.text_color_hex = color
            self.update_preview()

    def update_preview(self):
        preview_w, preview_h = 300, 533
        base_img = None

        if self.pack_cards:
            v_path = self.pack_cards[0]["video_var"].get().strip()
            if v_path and os.path.exists(v_path):
                base_img = extract_first_frame(v_path, preview_w, preview_h)

        if base_img is None:
            base_img = PIL.Image.new("RGB", (preview_w, preview_h), (40, 40, 40))

        first_text = ""
        if self.pack_cards:
            first_text = self.pack_cards[0]["text"].get("1.0", "end-1c")

        font_scale = self.size_slider.get()
        y_pct = self.y_slider.get()
        font_path = self.get_current_font()

        if first_text:
            overlay = draw_text_overlay(
                first_text, preview_w, preview_h, font_scale, y_pct, 
                self.bg_color_hex, self.text_color_hex, font_path
            )
            base_img.paste(overlay, (0, 0), overlay)

        ctk_img = ctk.CTkImage(light_image=base_img, dark_image=base_img, size=(270, 480))
        self.preview_label.configure(image=ctk_img)

    def log(self, message: str):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def cancel_process(self):
        if not self.is_cancelled:
            self.is_cancelled = True
            self.log("🛑 Отмена процесса...")
            self.stop_btn.configure(state="disabled")

    def start_process_thread(self):
        count_str = self.count_entry.get().strip()
        target_dir = self.folder_entry.get().strip()

        if not count_str.isdigit():
            self.log("⚠️ Укажите корректное число фонов!")
            return

        packs_data = []
        for idx, card in enumerate(self.pack_cards, 1):
            q = card["query"].get().strip()
            v_path = card["video_var"].get().strip()
            t = card["text"].get("1.0", "end-1c")
            a_path = card["audio_var"].get().strip()
            a_vol = card["audio_vol"].get()

            if not q or not v_path or not os.path.exists(v_path):
                self.log(f"⚠️ Ошибка в Пак №{idx}: Заполните запрос и выберите видео файл!")
                return
            
            packs_data.append({
                "query": q,
                "video": v_path,
                "text": t,
                "audio": a_path,
                "volume": a_vol
            })

        self.is_cancelled = False
        self.start_btn.configure(state="disabled")
        self.add_pack_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress_bar.set(0)

        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

        threading.Thread(
            target=self.run_pipeline, 
            args=(packs_data, int(count_str), target_dir), 
            daemon=True
        ).start()

    def download_pinterest_images(self, query: str, limit: int) -> list:
        urls = set()
        downloaded_paths = []
        temp_dir = os.path.join(os.getcwd(), "temp_downloaded")
        os.makedirs(temp_dir, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(f"https://www.pinterest.com/search/pins/?q={query}")

            attempts = 0
            target_urls_count = max(limit * 2, limit + 10)
            while len(urls) < target_urls_count and attempts < 60:
                if self.is_cancelled:
                    break
                
                page.evaluate("window.scrollBy(0, 1200)")
                time.sleep(1.2)
                attempts += 1

                for img in page.query_selector_all('img[src*="pinimg.com"]'):
                    src = img.get_attribute("src")
                    if src and any(size in src for size in ["236x", "474x", "736x"]):
                        high_res = re.sub(r'/(236x|474x|736x)/', '/originals/', src)
                        urls.add(high_res)
                        if len(urls) >= target_urls_count:
                            break

            browser.close()

        for url in list(urls):
            if len(downloaded_paths) >= limit or self.is_cancelled:
                break
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    filepath = os.path.join(temp_dir, f"bg_{int(time.time())}_{uuid.uuid4().hex[:5]}.jpg")
                    with open(filepath, 'wb') as f:
                        f.write(res.content)
                    downloaded_paths.append(filepath)
            except Exception as e:
                self.log(f"⚠️ Пропуск битой ссылки, беру следующую... ({e})")

        return downloaded_paths

    def run_pipeline(self, packs_data: list, per_pack_limit: int, target_dir: str):
        main_output_folder = os.path.join(target_dir, f"Batch_Packs_{int(time.time())}")
        os.makedirs(main_output_folder, exist_ok=True)

        total_packs = len(packs_data)
        total_videos_to_make = total_packs * per_pack_limit
        global_counter = 0

        font_scale = self.size_slider.get()
        y_pct = self.y_slider.get()
        font_path = self.get_current_font()

        try:
            for pack_idx, pack_info in enumerate(packs_data, 1):
                if self.is_cancelled: break

                current_query = pack_info["query"]
                fg_video_path = pack_info["video"]
                current_text = pack_info["text"]
                custom_audio_path = pack_info["audio"]
                audio_vol = pack_info["volume"]

                clean_query = re.sub(r'[\\/*?:"<>|]', "", current_query).strip().replace(" ", "_")

                self.log(f"\n📦 [Пакет {pack_idx}/{total_packs}]")
                self.log(f" ├ Видео: {os.path.basename(fg_video_path)}")
                self.log(f" ├ Запрос Pinterest: '{current_query}'")
                self.log(f" └ Ищем и скачиваем {per_pack_limit} картинок...")

                bgs = self.download_pinterest_images(current_query, per_pack_limit)

                if not bgs:
                    self.log(f"⚠️ Фоны по запросу '{current_query}' не найдены, пропускаем пак...")
                    continue

                self.log(f" └ Скачано фонов: {len(bgs)} из {per_pack_limit}. Прямой рендеринг через FFmpeg...")

                text_overlay_path = None
                if current_text:
                    w, h = get_video_dimensions(fg_video_path)
                    text_pil_img = draw_text_overlay(
                        current_text, w, h, font_scale, y_pct, 
                        self.bg_color_hex, self.text_color_hex, font_path
                    )
                    text_overlay_path = f"temp_text_{uuid.uuid4().hex[:6]}.png"
                    text_pil_img.save(text_overlay_path)

                for v_idx, bg_path in enumerate(bgs, 1):
                    if self.is_cancelled: break

                    set_folder_path = os.path.join(main_output_folder, f"Folder_{v_idx:02d}")
                    os.makedirs(set_folder_path, exist_ok=True)

                    output_name = f"Pack_{pack_idx:02d}_{clean_query}.mp4"
                    output_path = os.path.join(set_folder_path, output_name)
                    
                    global_counter += 1
                    self.log(f"  🎬 [{global_counter}/{total_videos_to_make}] Быстрый рендер в Folder_{v_idx:02d}/{output_name}...")

                    try:
                        unique_params = generate_unique_ffmpeg_params()
                        render_video_ffmpeg(
                            bg_path=bg_path,
                            fg_video_path=fg_video_path,
                            text_overlay_path=text_overlay_path,
                            audio_path=custom_audio_path,
                            audio_vol=audio_vol,
                            output_path=output_path,
                            ffmpeg_params=unique_params
                        )

                        self.progress_bar.set(global_counter / total_videos_to_make)

                    except Exception as e:
                        self.log(f"❌ Ошибка рендеринга {output_name}: {e}")

                    if os.path.exists(bg_path):
                        os.remove(bg_path)

                if text_overlay_path and os.path.exists(text_overlay_path):
                    os.remove(text_overlay_path)

            if not self.is_cancelled:
                self.log(f"\n🎉 ВСЕ ПАКИ УСПЕШНО СГЕНЕРИРОВАНЫ!\nСохранено в:\n{os.path.abspath(main_output_folder)}")

        except Exception as e:
            self.log(f"\n❌ Ошибка: {e}")

        finally:
            self.start_btn.configure(state="normal")
            self.add_pack_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")


if __name__ == "__main__":
    app = UniqueVideoGeneratorApp()
    app.mainloop()