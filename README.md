# SubLocalizer

**SubLocalizer**, `.ass` formatındaki altyazı dosyalarını biçimlendirme etiketlerini (tags) bozmadan otomatik olarak çeviren, modern ve kompakt bir masaüstü uygulamasıdır.

**SubLocalizer** is a modern and compact desktop application that automatically translates `.ass` subtitle files without breaking formatting tags.

---

## 🇹🇷 Türkçe

### Özellikler
*   **Akıllı Etiket Koruma:** Altyazılarınızdaki renk, konum ve stil kodlarını (`{\an8}`, `{\c&H000000&}` vb.) korur. Çeviri sırasında bu kodlar maskelenir ve bozulmaz.
*   **Çoklu Çeviri Motoru:**
    *   **Google Translate:** Çoklu sunucu desteği ve Lingva yedeklemesi ile hızlı ve ücretsiz.
    *   **DeepL Web:** API anahtarı gerektirmeden, web arayüzünü kullanarak yüksek kaliteli çeviri (Ücretsiz).
    *   **DeepL API:** Resmi DeepL API (Free ve Pro) desteği.
*   **Modern Arayüz:** PyQt6 ile geliştirilmiş, karanlık temalı, sürükle-bırak destekli kompakt tasarım.
*   **Otomatik Dil Algılama:** Kaynak dili otomatik tanır.
*   **Toplu İşlem:** Arka planda asenkron çalışarak arayüzü dondurmaz.
*   **Taşınabilir (Portable):** Kurulum gerektirmez, tek bir `.exe` dosyası olarak çalışır.

### Kurulum ve Kullanım
1.  [Releases](https://github.com/user/SubLocalizer/releases) sayfasından son sürümü indirin (`SubLocalizer.exe`).
2.  Programı çalıştırın.
3.  `.ass` dosyanızı pencerenin üzerine sürükleyin veya dosyayı seçin.
4.  Hedef dili seçin (Örn: Turkish).
5.  Çeviri motorunu seçin (Google Translate önerilir).
6.  **TRANSLATE** butonuna basın.
7.  Çevrilen dosya, orijinal dosyanın yanına `_tr.ass` (veya seçilen dil kodu) uzantısı ile kaydedilir.

### Geliştiriciler İçin
Bu projeyi geliştirmek isterseniz:

```bash
# Depoyu klonlayın
git clone https://github.com/user/SubLocalizer.git
cd SubLocalizer

# Sanal ortam oluşturun
python -m venv .venv
.venv\Scripts\activate

# Bağımlılıkları yükleyin
pip install -r requirements.txt

# Uygulamayı başlatın
python main.py
```

---

## 🇬🇧 English

### Features
*   **Smart Tag Preservation:** Preserves style, position, and color codes (`{\an8}`, `{\c&H000000&}`, etc.) in your subtitles. These tags are masked during translation to prevent corruption.
*   **Multiple Translation Engines:**
    *   **Google Translate:** Fast and free with multi-endpoint support and Lingva fallback.
    *   **DeepL Web:** High-quality translation using the web interface without an API key (Free).
    *   **DeepL API:** Support for official DeepL API (Free and Pro).
*   **Modern UI:** Compact, dark-themed design built with PyQt6, supporting Drag & Drop.
*   **Auto Language Detection:** Automatically detects the source language.
*   **Batch Processing:** Runs asynchronously in the background without freezing the UI.
*   **Portable:** No installation required, runs as a single `.exe` file.

### Installation & Usage
1.  Download the latest version (`SubLocalizer.exe`) from the [Releases](https://github.com/user/SubLocalizer/releases) page.
2.  Run the application.
3.  Drag & drop your `.ass` file onto the window or click to browse.
4.  Select the target language (e.g., Turkish).
5.  Select the translation engine (Google Translate is recommended).
6.  Click the **TRANSLATE** button.
7.  The translated file will be saved next to the original file with a `_tr.ass` (or selected lang code) suffix.

### For Developers
If you want to contribute:

```bash
# Clone the repository
git clone https://github.com/user/SubLocalizer.git
cd SubLocalizer

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

---

### License
MIT License
