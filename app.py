"""
Instagram DM AI Botu - Araba Paspası E-Ticaret
===============================================
Kurulum: pip install flask requests gspread google-auth google-generativeai
Çalıştırma: python app.py
"""

import os
import json
import sqlite3
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)
DB_DOSYASI = "konusmalar.db"
_sheets_client = None
_kalip_onbellek = {"veri": [], "son_guncelleme": 0}

# ============================================================
# ⚙️  AYARLAR
# ============================================================
VERIFY_TOKEN      = "benim_gizli_token_123"
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
SHEETS_CSV_URL    = os.getenv("SHEETS_CSV_URL", "")
SIPARIS_SHEET_ID  = "1MhhTzCV4vc33fB50JyOnaDX2P5t7OWZ6yP1aoOWmpXQ"
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

# Gemini yapılandırması
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")


# ============================================================
# 📊 KALIP LİSTESİ
# ============================================================
def kalip_listesi_yukle():
    simdi = time.time()
    if _kalip_onbellek["veri"] and (simdi - _kalip_onbellek["son_guncelleme"]) < 3600:
        return _kalip_onbellek["veri"]
    if not SHEETS_CSV_URL:
        return []
    try:
        resp = requests.get(SHEETS_CSV_URL, timeout=5)
        resp.encoding = "utf-8"
        satirlar = resp.text.strip().split("\n")
        basliklar = [k.strip() for k in satirlar[0].split(",")]
        kayitlar = []
        for satir in satirlar[1:]:
            kolonlar = [k.strip() for k in satir.split(",")]
            if len(kolonlar) >= 7 and kolonlar[0]:
                kayitlar.append(dict(zip(basliklar, kolonlar)))
        _kalip_onbellek["veri"] = kayitlar
        _kalip_onbellek["son_guncelleme"] = simdi
        print(f"✅ Kalıp listesi yüklendi: {len(kayitlar)} kayıt")
        return kayitlar
    except Exception as e:
        print(f"❌ Sheets hatası: {e}")
        return []


def kalip_ara(arama: str) -> str:
    kayitlar = kalip_listesi_yukle()
    if not kayitlar:
        return "(Kalıp listesi yüklenemedi)"

    arama_lower = arama.lower().strip()
    if not arama_lower:
        markalar = sorted(set(k.get("MARKA", "") for k in kayitlar if k.get("MARKA")))
        return "Kalıbımız olan markalar:\n" + ", ".join(markalar)

    # Yazım toleransı için basit eşleştirme
    eslesme = []
    for k in kayitlar:
        metin = " ".join([
            k.get("MARKA", ""), k.get("MODEL", ""),
            k.get("KASA KODU", ""), k.get("EK BİLGİ", "")
        ]).lower()

        # Kelime kelime ara
        kelimeler = arama_lower.split()
        if all(any(kelime in metin for kelime in [k2]) for k2 in kelimeler):
            eslesme.append(k)

    if not eslesme:
        # Daha geniş arama
        for k in kayitlar:
            metin = " ".join([k.get("MARKA", ""), k.get("MODEL", ""), k.get("KASA KODU", "")]).lower()
            for kelime in arama_lower.split():
                if len(kelime) > 2 and kelime in metin:
                    if k not in eslesme:
                        eslesme.append(k)

    if not eslesme:
        return f"'{arama}' için kalıp listesinde sonuç bulunamadı."

    basliklar = ["MARKA", "MODEL", "KASA KODU", "EK BİLGİ", "BAŞLANGIÇ", "BİTİŞ", "KALIP NO", "SOL AYAK", "BAGAJ", "ARKA ", "EK PARÇA", "NOT"]
    sonuc = f"'{arama}' için {len(eslesme)} sonuç:\n"
    for e in eslesme[:10]:
        satir = " | ".join(str(e.get(b, "")) for b in basliklar)
        sonuc += satir + "\n"
    return sonuc


# ============================================================
# 📊 SİPARİŞ KAYDET
# ============================================================
def sheets_baglanti():
    global _sheets_client
    if _sheets_client:
        return _sheets_client
    try:
        creds_data = json.loads(GOOGLE_CREDS_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        _sheets_client = gspread.authorize(creds)
        return _sheets_client
    except Exception as e:
        print(f"❌ Sheets bağlantı hatası: {e}")
        return None


def siparis_kaydet(siparis: dict):
    try:
        gc = sheets_baglanti()
        if not gc:
            return False
        sh = gc.open_by_key(SIPARIS_SHEET_ID)
        ws = sh.get_worksheet(0)
        satirlar = ws.get_all_values()
        siparis_no = "0001" if len(satirlar) <= 1 else str(len(satirlar)).zfill(4)
        tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
        satir = [
            siparis_no, tarih,
            siparis.get("kalip_no", ""), siparis.get("model", ""),
            siparis.get("yil", ""), siparis.get("paspas_rengi", ""),
            siparis.get("biye_rengi", ""), siparis.get("bagaj_rengi", ""),
            siparis.get("bagaj_biye_rengi", ""), siparis.get("ek_parca", ""),
            siparis.get("topukluk", ""), siparis.get("sofor", ""),
            siparis.get("on_yolcu", ""), siparis.get("saft", ""),
            siparis.get("sag", ""), siparis.get("sol", ""),
            siparis.get("bagaj", ""), siparis.get("logo_adet", ""),
            siparis.get("odeme_turu", ""), siparis.get("tutar", ""),
            siparis.get("not", ""), siparis.get("isim_soyisim", ""),
            siparis.get("telefon", ""), siparis.get("adres", ""),
            siparis.get("il", ""), siparis.get("ilce", ""), ""
        ]
        ws.append_row(satir)
        print(f"✅ Sipariş kaydedildi: #{siparis_no}")
        return siparis_no
    except Exception as e:
        print(f"❌ Sipariş kayıt hatası: {e}")
        return False


# ============================================================
# 🗄️ VERİTABANI
# ============================================================
def veritabani_baslat():
    conn = sqlite3.connect(DB_DOSYASI)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mesajlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_id TEXT NOT NULL,
            rol TEXT NOT NULL,
            icerik TEXT NOT NULL,
            tarih TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def gecmis_yukle(kullanici_id: str, son_kac: int = 8) -> list:
    conn = sqlite3.connect(DB_DOSYASI)
    rows = conn.execute("""
        SELECT rol, icerik FROM mesajlar
        WHERE kullanici_id = ?
        ORDER BY tarih DESC LIMIT ?
    """, (kullanici_id, son_kac)).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def mesaj_kaydet(kullanici_id: str, rol: str, icerik: str):
    conn = sqlite3.connect(DB_DOSYASI)
    conn.execute("INSERT INTO mesajlar (kullanici_id, rol, icerik) VALUES (?, ?, ?)", (kullanici_id, rol, icerik))
    conn.commit()
    conn.close()


# ============================================================
# 🤖 TEMEL PROMPT (KISA)
# ============================================================
TEMEL_PROMPT = """Sen araba paspası üreten bir mağazanın Instagram müşteri destek botusun.
Türkçe konuş, kısa ve samimi cevaplar ver, müşteriye "siz" de.
Kargo ücretsiz, üretim 3 iş günü, 1 yıl garanti, araca özel kalıp, A kalite malzeme.
Bireysel alımda indirim yok, toplu alımda var.
Sipariş DM'den alınır."""

RENKLER = """Paspas renkleri: KREM, AÇIK GRİ, KOYU GRİ, SİYAH, AÇIK TABA, TABA, KAHVERENGİ, BEJ, MAVİ, LACİVERT, TURUNCU, KIRMIZI, BORDO
Biye renkleri: MAVİ, KOYU KIRMIZI, SİYAH, AÇIK GRİ, ALTIN, KIRMIZI, KOYU GRİ, KOYU KAHVERENGİ, ASKER YEŞİLİ, KREM, BORDO, SARI, BEJ, LACİVERT, TURUNCU, FOSFOR YEŞİLİ, KOYU YEŞİL"""

SIPARIS_PROMPT = """Sipariş alırken sırayla topla: araç bilgisi, paspas rengi, biye rengi, bagaj paspası, arka yolcu paspası, ek parça, isim, telefon, adres.
Onay özetinde şablonu kullan:
"🚗 [ARAÇ] | 🎨 Paspas:[RENK] Biye:[RENK] | 📦 Bagaj:[VAR/YOK] Arka:[TEK/3] | 👤 [İSİM] | 📍 [İL/İLÇE] — Onaylıyor musunuz?"
Onay sonrası sadece şu JSON'u ekle:
###SIPARIS###{"kalip_no":"","model":"","yil":"","paspas_rengi":"","biye_rengi":"","bagaj_rengi":"","bagaj_biye_rengi":"","ek_parca":"","topukluk":"","sofor":"","on_yolcu":"","saft":"","sag":"","sol":"","bagaj":"","logo_adet":"","odeme_turu":"","tutar":"","not":"","isim_soyisim":"","telefon":"","adres":"","il":"","ilce":""}###SIPARIS_BITIS###"""


def ihtiyac_tespit(mesaj: str, gecmis: list) -> dict:
    """Mesajda ne gerekiyor tespit et"""
    mesaj_lower = mesaj.lower()
    tum_metin = mesaj_lower + " ".join(str(g.get("content","")) for g in gecmis).lower()

    arac_kelimeleri = ["passat", "golf", "tiguan", "polo", "bmw", "mercedes", "audi",
                       "toyota", "honda", "ford", "renault", "peugeot", "hyundai",
                       "kia", "fiat", "opel", "seat", "skoda", "volvo", "mazda",
                       "nissan", "mitsubishi", "suzuki", "dacia", "citroen", "alfa",
                       "corolla", "civic", "focus", "clio", "megane", "paspas", "kalıp",
                       "model", "araç", "araba", "var mı", "uyumlu"]

    renk_kelimeleri = ["renk", "rengi", "siyah", "kırmızı", "mavi", "gri", "bej",
                       "krem", "taba", "kahve", "bordo", "lacivert", "biye"]

    siparis_kelimeleri = ["sipariş", "almak", "satın", "istiyor", "fiyat", "ne kadar",
                          "adres", "telefon", "isim", "ödeme", "onay", "evet"]

    return {
        "kalip_ara": any(k in tum_metin for k in arac_kelimeleri),
        "renk_sor": any(k in mesaj_lower for k in renk_kelimeleri),
        "siparis": any(k in mesaj_lower for k in siparis_kelimeleri),
        "arama_terimi": mesaj  # Kalıp araması için orijinal mesaj
    }


# ============================================================
# 🤖 GEMİNİ CEVAP
# ============================================================
def siparis_json_parse(cevap: str):
    try:
        if "###SIPARIS###" in cevap and "###SIPARIS_BITIS###" in cevap:
            baslangic = cevap.index("###SIPARIS###") + len("###SIPARIS###")
            bitis = cevap.index("###SIPARIS_BITIS###")
            return json.loads(cevap[baslangic:bitis].strip())
    except:
        pass
    return None


def ai_cevap_uret(kullanici_id: str, mesaj: str) -> str:
    mesaj_kaydet(kullanici_id, "user", mesaj)
    gecmis = gecmis_yukle(kullanici_id, son_kac=8)

    # İhtiyaca göre dinamik prompt oluştur
    ihtiyac = ihtiyac_tespit(mesaj, gecmis)

    prompt = TEMEL_PROMPT

    if ihtiyac["renk_sor"]:
        prompt += "\n\n" + RENKLER

    if ihtiyac["siparis"]:
        prompt += "\n\n" + SIPARIS_PROMPT

    if ihtiyac["kalip_ara"]:
        kalip_sonucu = kalip_ara(ihtiyac["arama_terimi"])
        prompt += f"\n\nKALIP ARAMA SONUCU:\n{kalip_sonucu}"
        prompt += "\nKalıp varsa 'Kalıbımız mevcut' de. Yoksa 'Bu model için kalıbımız yok' de. Yıl çakışması varsa hangi kasa olduğunu sor."

    # Konuşma geçmişini düz metin olarak ekle
    gecmis_metin = ""
    for g in gecmis[:-1]:  # Son mesaj zaten var
        rol = "Müşteri" if g["role"] == "user" else "Bot"
        gecmis_metin += f"{rol}: {g['content']}\n"

    tam_prompt = f"{prompt}\n\nKonuşma geçmişi:\n{gecmis_metin}\nMüşteri: {mesaj}\nBot:"

    try:
        response = model.generate_content(tam_prompt)
        tam_cevap = response.text.strip()

        siparis_data = siparis_json_parse(tam_cevap)
        if siparis_data:
            siparis_no = siparis_kaydet(siparis_data)
            temiz_cevap = tam_cevap[:tam_cevap.index("###SIPARIS###")].strip()
            if siparis_no:
                temiz_cevap = temiz_cevap.replace("XXXX", str(siparis_no))
            mesaj_kaydet(kullanici_id, "assistant", temiz_cevap)
            return temiz_cevap

        mesaj_kaydet(kullanici_id, "assistant", tam_cevap)
        return tam_cevap

    except Exception as e:
        print(f"Gemini API hatası: {e}")
        return "Şu an teknik bir sorun yaşıyoruz. Lütfen daha sonra tekrar deneyin."


# ============================================================
# 📲 INSTAGRAM
# ============================================================
def instagram_mesaj_gonder(alici_id: str, mesaj: str) -> bool:
    url = "https://graph.instagram.com/v21.0/me/messages"
    payload = {"recipient": {"id": alici_id}, "message": {"text": mesaj}}
    headers = {"Authorization": f"Bearer {PAGE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        print(f"✅ Mesaj gönderildi: {alici_id}")
        return True
    print(f"❌ Gönderilemedi: {response.text}")
    return False


# ============================================================
# 🌐 WEBHOOK
# ============================================================
@app.route("/webhook", methods=["GET"])
def webhook_dogrula():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook doğrulandı!")
        return challenge, 200
    return "Doğrulama başarısız", 403


@app.route("/webhook", methods=["POST"])
def webhook_al():
    data = request.get_json()
    try:
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                gonderen_id = event.get("sender", {}).get("id")
                alici_id    = event.get("recipient", {}).get("id")
                if gonderen_id == alici_id:
                    continue
                mesaj = event.get("message", {})
                if "text" not in mesaj:
                    continue
                mesaj_metni = mesaj["text"]
                print(f"💬 ({gonderen_id}): {mesaj_metni}")
                cevap = ai_cevap_uret(gonderen_id, mesaj_metni)
                print(f"🤖 Bot: {cevap}")
                instagram_mesaj_gonder(gonderen_id, cevap)
    except Exception as e:
        print(f"❌ Hata: {e}")
    return json.dumps({"status": "ok"}), 200, {"Content-Type": "application/json"}


@app.route("/", methods=["GET"])
def ana_sayfa():
    return "🤖 Paspas Bot çalışıyor!"


if __name__ == "__main__":
    veritabani_baslat()
    kalip_listesi_yukle()
    print("🚀 Bot başlatılıyor...")
    app.run(host="0.0.0.0", port=5000, debug=True)
