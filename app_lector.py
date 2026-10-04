import io
import os
import re
import glob
import json
import threading
import time
import webbrowser
from collections import Counter
import customtkinter as ctk
import pdfplumber
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tkinter import filedialog, messagebox

# Archivo de configuración anclado a la carpeta del script (nunca se pierde)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# System instruction para Gemini (se define una sola vez)
SYSTEM_INSTRUCTION = """
Te enviaré la información y diapositivas de una ayuda visual / manual técnico de manufactura.
Tu tarea es procesarlas y generar un objeto JSON descargable que cumpla ESTRICTAMENTE con las siguientes reglas:

ESTRUCTURA JSON OBLIGATORIA:
Debe contener la llave "name" (nombre/código del manual) y la lista "steps" con los pasos.

REGLAS CRÍTICAS PARA "steps":

1. EXACTAMENTE UN PASO POR DIAPOSITIVA (OBLIGATORIO):
   - Cada sección "--- DIAPOSITIVA X/Y ---" enviada corresponde a UNA SOLA DIAPOSITIVA DE TRABAJO.
   - Debes generar EXACTAMENTE UN ELEMENTO en la lista "steps" por cada diapositiva enviada.
   - NUNCA dividas una diapositiva en múltiples pasos ni crees sub-pasos separados, aunque la diapositiva contenga incisos (1.1, 1.2, 1.3), notas o listas. Sintetiza y narra toda la diapositiva en una sola instrucción clara y breve.

2. FORMATO DE CADA ELEMENTO:
   - Debe iniciar obligatoriamente con el formato: "S[hoja]/[total] [Verbo en infinitivo + Acción breve]".
   - IMPORTANTE: No uses guión después del número de paso, pon únicamente un espacio entre S[n]/[total] y la acción.
   - Ejemplos exactos:
     "S1/50 Modelo a trabajar"
     "S2/50 Ingresar a QuickLinks y seleccionar edificio B4"
     "S7/50 Colocar el Loctite y Gasket"
     "S8/50 Colocar la barra de conexiones sobre el frame"
     "S50/50 unidad terminada"

3. FIDELIDAD Y BREVEDAD:
   - Mantén las frases extremadamente breves para evitar desbordamientos en pantalla móvil (Flutter UI).
   - Extrae la acción principal que realiza el operario en esa diapositiva.
"""

class ManualTemplate(BaseModel):
    name: str = Field(description="Nombre o código del manual (ejemplo: A-0011-00841 PRE-FRAME 2)")
    steps: list[str] = Field(description="Lista de pasos formateados exactamente como 'S[n]/[total] [Acción sintetizada del slide]'")

MODELOS_GEMINI = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest']

# Configuración de CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AppLector(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Extractor de Ayudas Visuales (IA)")
        self.geometry("800x550")
        self.resizable(False, False)

        # Estado interno
        self.api_key = self._load_config()
        self.client = None
        self.modelos_disponibles = []  # Lista de modelos compatibles
        self.modelo_actual_idx = 0     # Índice del modelo en uso

        # Configurar Grid principal
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # =========================================================
        # FRAME IZQUIERDO (Configuración)
        # =========================================================
        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, text="⚙️ Configuración",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.api_label = ctk.CTkLabel(self.sidebar_frame, text="Google Gemini API Key:")
        self.api_label.grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")

        self.api_entry = ctk.CTkEntry(
            self.sidebar_frame, placeholder_text="Pega tu API Key aquí", show="*"
        )
        self.api_entry.grid(row=2, column=0, padx=20, pady=(5, 10), sticky="ew")
        if self.api_key:
            self.api_entry.insert(0, self.api_key)

        self.save_api_btn = ctk.CTkButton(
            self.sidebar_frame, text="Guardar Llave", command=self.save_api_key
        )
        self.save_api_btn.grid(row=3, column=0, padx=20, pady=10)

        self.get_api_btn = ctk.CTkButton(
            self.sidebar_frame, text="🔑 Obtener API Key",
            fg_color="transparent", border_width=2,
            text_color=("gray10", "#DCE4EE"),
            command=self.open_google_ai_studio
        )
        self.get_api_btn.grid(row=4, column=0, padx=20, pady=10)

        # =========================================================
        # FRAME DERECHO (Procesamiento)
        # =========================================================
        self.main_frame = ctk.CTkFrame(self, corner_radius=10)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_rowconfigure(3, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.header_label = ctk.CTkLabel(
            self.main_frame, text="Extractor Automático de Plantillas",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.header_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.desc_label = ctk.CTkLabel(
            self.main_frame,
            text="Selecciona una carpeta con PDFs para extraer las instrucciones\nusando Inteligencia Artificial.",
            text_color="gray"
        )
        self.desc_label.grid(row=1, column=0, padx=20, pady=(0, 10))

        # Barra de progreso
        self.progress_bar = ctk.CTkProgressBar(self.main_frame, mode="determinate")
        self.progress_bar.grid(row=2, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.progress_bar.set(0)

        self.process_btn = ctk.CTkButton(
            self.main_frame, text="📂 Seleccionar Carpeta y Procesar",
            font=ctk.CTkFont(size=15, weight="bold"), height=50,
            command=self.start_processing_thread
        )
        self.process_btn.grid(row=3, column=0, padx=20, pady=10, sticky="n")

        # Consola / Logs
        self.log_box = ctk.CTkTextbox(self.main_frame, state="disabled", wrap="word")
        self.log_box.grid(row=4, column=0, padx=20, pady=(10, 20), sticky="nsew")

        # Inicializar modelos si ya hay API key guardada
        if self.api_key:
            self._init_model()

    # =================================================================
    # CONFIGURACIÓN
    # =================================================================

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f).get("api_key", "")
            except Exception:
                pass
        return ""

    def save_api_key(self):
        key = self.api_entry.get().strip()
        if not key:
            messagebox.showwarning("Atención", "La API Key no puede estar vacía.")
            return

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"api_key": key}, f)
            self.api_key = key
            self._init_model()
            messagebox.showinfo("Éxito", "API Key guardada correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar: {e}")

    def _init_model(self):
        """Configura la API y detecta TODOS los modelos compatibles."""
        if not self.api_key:
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as e:
            self.client = None
            return

        self.modelos_disponibles = []
        self.modelo_actual_idx = 0

        for nombre in MODELOS_GEMINI:
            try:
                self.client.models.generate_content(
                    model=nombre,
                    contents="test"
                )
                self.modelos_disponibles.append(nombre)
            except Exception:
                continue

    def open_google_ai_studio(self):
        webbrowser.open("https://aistudio.google.com/app/apikey")

    # =================================================================
    # LOGGING (Thread-Safe)
    # =================================================================

    def log_message(self, message):
        """Envía mensajes a la consola visual de forma segura desde cualquier hilo."""
        def _log():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _log)

    # =================================================================
    # PROCESAMIENTO
    # =================================================================

    def start_processing_thread(self):
        if not self.api_key:
            messagebox.showwarning("Atención", "Primero debes configurar y guardar tu API Key de Gemini.")
            return

        if not self.modelos_disponibles:
            self._init_model()
            if not self.modelos_disponibles:
                messagebox.showerror("Error", "No se encontró un modelo de Gemini compatible con tu API Key.")
                return

        self.modelo_actual_idx = 0

        folder_path = filedialog.askdirectory(title="Selecciona la carpeta con PDFs")
        if not folder_path:
            return

        self.process_btn.configure(state="disabled", text="Procesando...")
        self.progress_bar.set(0)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        thread = threading.Thread(target=self._process_pdfs, args=(folder_path,), daemon=True)
        thread.start()

    def _prepare_payload_and_clean_text(self, pdf):
        """
        Analiza las páginas del PDF:
        1. Filtra portadas, contraportadas y hojas de control de documentos que no contengan 'Hoja X de Y'.
        2. Elimina encabezados/pies de página repetidos (boilerplate en >= 35% de diapositivas).
        3. Prepara la carga para Gemini garantizando la correspondencia 1-a-1 por diapositiva.
        """
        total_paginas_pdf = len(pdf.pages)
        if total_paginas_pdf == 0:
            return [], [], 0, 0, 0

        work_pages = []
        max_detected_total = 0

        # 1. Identificar páginas de trabajo válidas (excluyendo portadas y registros de control)
        for idx, page in enumerate(pdf.pages, start=1):
            txt = page.extract_text() or ""
            txt_lower = txt.lower()

            # Buscar patrón de diapositiva de trabajo: "Hoja X de Y"
            match = re.search(r'Hoja\s+(\d+)\s+de\s+(\d+)', txt, re.IGNORECASE)

            if match:
                h_num = int(match.group(1))
                t_num = int(match.group(2))
                max_detected_total = max(max_detected_total, t_num)
                work_pages.append((idx, page, txt, h_num, t_num))
            else:
                # Filtrar portadas y contraportadas explícitas
                is_cover = any(kw in txt_lower for kw in [
                    "guadalajara document control",
                    "document title",
                    "document number",
                    "date information",
                    "release date",
                    "document information",
                    "document type",
                    "revision"
                ])
                if not is_cover and len(txt.strip()) > 40:
                    work_pages.append((idx, page, txt, None, None))

        if not work_pages:
            return [], [], 0, 0, 0

        total_work_slides = len(work_pages)
        final_total = max_detected_total if max_detected_total > 0 else total_work_slides

        cleaned_work_pages = []
        raw_texts_for_boilerplate = []

        for i, (idx, page, txt, h_num, t_num) in enumerate(work_pages, start=1):
            actual_h = h_num if h_num is not None else i
            actual_t = t_num if t_num is not None else final_total
            cleaned_work_pages.append((idx, page, txt, actual_h, actual_t))
            raw_texts_for_boilerplate.append(txt)

        # 2. Filtrar boilerplate repetido
        line_counts = Counter()
        for txt in raw_texts_for_boilerplate:
            lines = set(line.strip() for line in txt.splitlines() if line.strip())
            for line in lines:
                line_counts[line] += 1

        threshold = max(2, int(len(cleaned_work_pages) * 0.35))
        boilerplate = {line for line, count in line_counts.items() if count >= threshold}

        contents_payload = []
        slide_meta = []
        hojas_texto = 0
        hojas_imagen = 0

        for idx, page, raw_text, h_num, t_num in cleaned_work_pages:
            filtered_lines = [
                line.strip() for line in raw_text.splitlines()
                if line.strip() and line.strip() not in boilerplate
            ]
            texto_limpio = "\n".join(filtered_lines).strip()
            texto_limpio = re.sub(r'\n{3,}', '\n\n', texto_limpio)

            tag_header = f"\n--- DIAPOSITIVA {h_num}/{t_num} (Hoja {h_num} de {t_num}) ---\n"
            slide_meta.append((h_num, t_num))

            if len(texto_limpio) >= 15:
                contents_payload.append(f"{tag_header}{texto_limpio}")
                hojas_texto += 1
            else:
                try:
                    img = page.to_image(resolution=120).original
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=80)
                    img_bytes = buf.getvalue()

                    contents_payload.append(f"{tag_header}[CONTENIDO VISUAL DE LA DIAPOSITIVA]")
                    contents_payload.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
                    hojas_imagen += 1
                except Exception:
                    contents_payload.append(f"{tag_header}Sin contenido textual")

        omitted_pages = total_paginas_pdf - total_work_slides
        return contents_payload, slide_meta, hojas_texto, hojas_imagen, omitted_pages

    def _post_process_steps(self, resultado, slide_meta):
        """Asegura la correspondencia 1-a-1 de pasos por diapositiva y el formato estricto S[n]/[total] [acción]."""
        if not resultado or "steps" not in resultado:
            return resultado

        steps = resultado.get("steps", [])
        new_steps = []

        for i, (h_num, t_num) in enumerate(slide_meta):
            if i < len(steps):
                raw_step = steps[i]
                # Limpiar prefijos existentes como "S1/50 - ", "S1/50: ", "S1/50 ", "1.- ", "1. "
                cleaned_text = re.sub(r'^S\d+/\d+\s*[-:]?\s*', '', raw_step).strip()
                cleaned_text = re.sub(r'^\d+[\.-]\s*', '', cleaned_text).strip()
            else:
                cleaned_text = "Continuar operación de la diapositiva"

            new_steps.append(f"S{h_num}/{t_num} {cleaned_text}")

        resultado["steps"] = new_steps
        return resultado

    def _call_gemini(self, contents_payload, slide_meta, nombre_base):
        """Envía el contenido (texto e imágenes) a Gemini con reintentos automáticos y rotación de modelos."""
        if not self.client:
            self.log_message("  -> ❌ El cliente de Gemini no está configurado.")
            return None

        prompt_header = f"Nombre del manual: {nombre_base}\nCONTENIDO DE LAS DIAPOSITIVAS DE TRABAJO:\n"
        contents = [prompt_header] + contents_payload
        max_reintentos = 3

        for intento in range(max_reintentos):
            if self.modelo_actual_idx >= len(self.modelos_disponibles):
                self.log_message("  -> ❌ Se agotaron todos los modelos disponibles.")
                return None

            nombre_modelo = self.modelos_disponibles[self.modelo_actual_idx]

            try:
                response = self.client.models.generate_content(
                    model=nombre_modelo,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=ManualTemplate,
                    )
                )
                if response.text:
                    res_json = json.loads(response.text.strip())
                    return self._post_process_steps(res_json, slide_meta)
                return None

            except Exception as e:
                error_str = str(e)

                if '429' in error_str:
                    if 'PerDay' in error_str:
                        self.log_message(f"  -> ⚠️ Límite diario alcanzado en {nombre_modelo}.")
                        self.modelo_actual_idx += 1
                        if self.modelo_actual_idx < len(self.modelos_disponibles):
                            nuevo_nombre = self.modelos_disponibles[self.modelo_actual_idx]
                            self.log_message(f"  -> 🔄 Cambiando a modelo: {nuevo_nombre}")
                            continue
                        else:
                            self.log_message("  -> ❌ Se agotaron todos los modelos disponibles.")
                            return None
                    else:
                        match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
                        espera = float(match.group(1)) if match else 30.0
                        self.log_message(f"  -> ⏳ Límite por minuto. Esperando {espera:.0f}s...")
                        time.sleep(espera + 1)
                        continue
                else:
                    self.log_message(f"  -> ❌ Error de IA: {error_str}")
                    return None

        self.log_message("  -> ❌ Se agotaron los reintentos.")
        return None

    def _process_pdfs(self, folder_path):
        try:
            archivos_pdf = glob.glob(os.path.join(folder_path, '*.pdf'))

            if not archivos_pdf:
                self.log_message("❌ No se encontraron archivos PDF en la carpeta seleccionada.")
                return

            total_pdfs = len(archivos_pdf)
            self.log_message(f"🔍 Se encontraron {total_pdfs} archivos PDF.\n")

            last_request_time = 0
            exitosos = 0
            fallidos = 0

            for idx, ruta_pdf in enumerate(archivos_pdf, start=1):
                nombre_base = os.path.splitext(os.path.basename(ruta_pdf))[0]
                nombre_json = os.path.join(folder_path, f"{nombre_base}.json")

                self.log_message(f"📄 [{idx}/{total_pdfs}] Procesando: {os.path.basename(ruta_pdf)} ...")

                try:
                    # 1. Extraer y optimizar páginas (Texto limpio + Fallback a imagen de ser necesario)
                    with pdfplumber.open(ruta_pdf) as pdf:
                        if len(pdf.pages) == 0:
                            self.log_message("  -> PDF sin hojas, ignorando.\n")
                            continue

                        contents_payload, slide_meta, h_texto, h_imagen, h_omitidas = self._prepare_payload_and_clean_text(pdf)

                    if not contents_payload:
                        self.log_message("  -> ⚠️ No se encontró contenido de trabajo válido en el PDF.\n")
                        fallidos += 1
                        continue

                    msg_info = f"  -> 📊 {len(slide_meta)} diapositivas de trabajo reconocidas"
                    if h_omitidas > 0:
                        msg_info += f" ({h_omitidas} portadas/contraportadas omitidas)"
                    self.log_message(msg_info)

                    if h_imagen > 0:
                        self.log_message(f"  -> 📄 {h_texto} por texto | 👁️ {h_imagen} por Visión (Imágenes)")

                    # Rate-Limiting Dinámico
                    espera = 4.0 - (time.time() - last_request_time)
                    if espera > 0:
                        time.sleep(espera)

                    # 2. Enviar a Gemini
                    self.log_message("  -> Analizando con Inteligencia Artificial...")
                    last_request_time = time.time()
                    resultado = self._call_gemini(contents_payload, slide_meta, nombre_base)

                    if resultado and "steps" in resultado:
                        with open(nombre_json, 'w', encoding='utf-8') as f:
                            json.dump(resultado, f, ensure_ascii=False, indent=2)

                        self.log_message(f"  -> ✅ ¡Listo! {len(resultado['steps'])} pasos generados.")
                        self.log_message(f"  -> Guardado como: {os.path.basename(nombre_json)}\n")
                        exitosos += 1
                    else:
                        self.log_message("  -> ❌ Falló la generación del JSON.\n")
                        fallidos += 1

                except Exception as e:
                    self.log_message(f"  -> ❌ Error procesando PDF: {e}\n")
                    fallidos += 1

                # Actualizar barra de progreso
                self.after(0, lambda v=idx/total_pdfs: self.progress_bar.set(v))

            self.log_message(f"🎉 ¡Proceso finalizado! ✅ {exitosos} exitosos | ❌ {fallidos} fallidos")

        except Exception as e:
            self.log_message(f"❌ Error general: {e}")
        finally:
            self.after(0, lambda: self.process_btn.configure(
                state="normal", text="📂 Seleccionar Carpeta y Procesar"
            ))


if __name__ == "__main__":
    app = AppLector()
    app.mainloop()
