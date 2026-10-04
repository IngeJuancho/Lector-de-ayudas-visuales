# Extractor de Ayudas Visuales (IA) 🛠️🤖

Aplicación gráfica desarrollada en Python (CustomTkinter) que automatiza la extracción y estandarización de instrucciones paso a paso desde manuales técnicos y ayudas visuales en PDF (usados por operarios en plantas de manufactura) para generar plantillas estructuradas en formato JSON compatibles con la aplicación **TimeLog** (Flutter).

---

## 🌟 Características Principales

* **Filtro Inteligente de Portadas**: Detecta la numeración de diapositivas de trabajo (`Hoja X de Y`) y omite automáticamente portadas administrativas (como *Document Control*, registros de revisiones y registros de firmas).
* **1 Slide = 1 Paso NARRADO**: Sintetiza todos los incisos, diagramas y notas de una diapositiva en un único paso claro y breve (`S1/N`, `S2/N`, ..., `SN/N`).
* **Soporte Híbrido Multimodal (Visión AI)**: 
  - *Modo Texto*: Procesa el texto vectorial del PDF de forma ultra rápida y económica.
  - *Modo Visión (Fallback)*: Si una diapositiva es un esquema, foto o captura sin texto legible, la convierte a imagen JPEG y la procesa con las capacidades de visión de **Google Gemini AI**.
* **Integración con `google-genai` SDK**: Utiliza esquemas Pydantic (`response_schema`) para garantizar salidas JSON 100% válidas.
* **Tolerancia a Fallos y Rotación de Modelos**: Maneja automáticamente cuotas de API (Error 429) con espera adaptativa y rotación de modelos (`gemini-2.5-flash`, `gemini-2.0-flash`).
* **Interfaz Gráfica Moderna**: Construida con `CustomTkinter` en modo oscuro, barra de progreso y consola visual de logs.

---

## 🚀 Requisitos e Instalación

### Requisitos Prerequisitos
- Python 3.10+
- Una API Key gratuita de [Google AI Studio](https://aistudio.google.com/app/apikey).

### Instalación de Dependencias
```bash
pip install customtkinter pdfplumber google-genai pydantic pillow
```

---

## 💻 Uso

1. Ejecuta la aplicación:
   ```bash
   python app_lector.py
   ```
2. Pega tu **Google Gemini API Key** en el panel izquierdo y haz clic en **Guardar Llave**.
3. Haz clic en **📂 Seleccionar Carpeta y Procesar** y selecciona la carpeta con tus archivos PDF.
4. El programa generará un archivo `.json` homónimo junto a cada PDF listo para consumirse en la app **TimeLog**.

---

## 📦 Compilación a Ejecutable Standalone (.exe)

Para compilar una versión portátil sin necesidad de tener Python instalado en la máquina destino:

```bash
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --collect-all customtkinter --exclude-module torch --exclude-module torchvision --exclude-module scipy --exclude-module pandas --exclude-module matplotlib --exclude-module sympy --exclude-module sqlalchemy --exclude-module lxml --name "ExtractorAyudasVisuales" app_lector.py
```
El ejecutable optimizado se generará dentro de `dist/ExtractorAyudasVisuales/ExtractorAyudasVisuales.exe`.
