"""
Instagram DM AI Botu - Araba Paspası E-Ticaret
===============================================
Kurulum: pip install flask anthropic requests gspread google-auth openpyxl
Çalıştırma: python app.py
"""

import os
import json
import hmac
import hashlib
import sqlite3
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import anthropic
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)
DB_DOSYASI = "konusmalar.db"

# Stok önbelleği (5 dakikada bir güncellenir)
_stok_onbellek = {"veri": None, "son_guncelleme": 0}
_sheets_client = None

# ============================================================
# ⚙️  BURAYA KENDİ BİLGİLERİNİ GİR
# ============================================================
VERIFY_TOKEN      = "benim_gizli_token_123"
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
APP_SECRET        = os.getenv("APP_SECRET", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SHEETS_CSV_URL    = os.getenv("SHEETS_CSV_URL", "")          # Kalıp listesi CSV linki
SIPARIS_SHEET_ID  = "1MhhTzCV4vc33fB50JyOnaDX2P5t7OWZ6yP1aoOWmpXQ"  # Sipariş Sheets ID
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")       # JSON içeriği (Railway'e ekle)


# ============================================================
# 📊 GOOGLE SHEETS BAĞLANTISI
# ============================================================
def sheets_baglanti():
    """Google Sheets servis hesabı bağlantısı"""
    global _sheets_client
    if _sheets_client:
        return _sheets_client
    try:
        creds_data = json.loads(GOOGLE_CREDS_JSON)
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        _sheets_client = gspread.authorize(creds)
        return _sheets_client
    except Exception as e:
        print(f"❌ Sheets bağlantı hatası: {e}")
        return None


def siparis_no_olustur(ws) -> str:
    """Son sipariş numarasına göre yeni numara üret"""
    try:
        satirlar = ws.get_all_values()
        if len(satirlar) <= 1:
            return "0001"
        son_satir = satirlar[-1]
        if son_satir and son_satir[0] and son_satir[0].isdigit():
            return str(int(son_satir[0]) + 1).zfill(4)
        return str(len(satirlar)).zfill(4)
    except:
        return str(int(time.time()))[-4:]


def siparis_kaydet(siparis: dict) -> bool:
    """Siparişi Google Sheets'e kaydet"""
    try:
        gc = sheets_baglanti()
        if not gc:
            return False

        sh = gc.open_by_key(SIPARIS_SHEET_ID)
        ws = sh.get_worksheet(0)

        siparis_no = siparis_no_olustur(ws)
        tarih = datetime.now().strftime("%d.%m.%Y %H:%M")

        # Sütun sırası: SİPARİŞ NO, TARİH, KALIP NO, MODEL, YILI,
        # PASPAS RENGİ, BİYE RENGİ, BAGAJ RENGİ, BAGAJ PASPASI BİYE RENGİ,
        # EK PARÇA, TOPUKLUK, ŞOFÖR, ÖN YOLCU, ŞAFT, SAĞ, SOL, BAGAJ,
        # LOGO ADET, ÖDEME TÜRÜ, TUTAR, NOT, İSİM SOYİSİM, TELEFON,
        # ADRES, İL, İLÇE, BOŞ BIRAK
        satir = [
            siparis_no,
            tarih,
            siparis.get("kalip_no", ""),
            siparis.get("model", ""),
            siparis.get("yil", ""),
            siparis.get("paspas_rengi", ""),
            siparis.get("biye_rengi", ""),
            siparis.get("bagaj_rengi", ""),
            siparis.get("bagaj_biye_rengi", ""),
            siparis.get("ek_parca", ""),
            siparis.get("topukluk", ""),
            siparis.get("sofor", ""),
            siparis.get("on_yolcu", ""),
            siparis.get("saft", ""),
            siparis.get("sag", ""),
            siparis.get("sol", ""),
            siparis.get("bagaj", ""),
            siparis.get("logo_adet", ""),
            siparis.get("odeme_turu", ""),
            siparis.get("tutar", ""),
            siparis.get("not", ""),
            siparis.get("isim_soyisim", ""),
            siparis.get("telefon", ""),
            siparis.get("adres", ""),
            siparis.get("il", ""),
            siparis.get("ilce", ""),
            ""  # BOŞ BIRAK
        ]

        ws.append_row(satir)
        print(f"✅ Sipariş kaydedildi: #{siparis_no}")
        return siparis_no

    except Exception as e:
        print(f"❌ Sipariş kayıt hatası: {e}")
        return False


# ============================================================
# 📊 GOOGLE SHEETS KALIP LİSTESİ
# ============================================================
def kalip_listesi_cek() -> str:
    simdi = time.time()
    if _stok_onbellek["veri"] and (simdi - _stok_onbellek["son_guncelleme"]) < 300:
        return _stok_onbellek["veri"]

    if not SHEETS_CSV_URL:
        return "(Kalıp listesi bağlantısı henüz kurulmamış)"

    try:
        resp = requests.get(SHEETS_CSV_URL, timeout=5)
        resp.encoding = "utf-8"
        satirlar = resp.text.strip().split("\n")

        liste = "=== KALIP LİSTESİ ===\n"
        liste += "Sütunlar: MARKA | MODEL | KASA KODU | EK BİLGİ | BAŞLANGIÇ | BİTİŞ | KALIP NO | SOL AYAK | BAGAJ | ARKA | EK PARÇA | NOT\n\n"

        for satir in satirlar[1:]:
            kolonlar = [k.strip() for k in satir.split(",")]
            if len(kolonlar) < 7 or not kolonlar[0]:
                continue
            liste += " | ".join(kolonlar[:12]) + "\n"

        _stok_onbellek["veri"] = liste
        _stok_onbellek["son_guncelleme"] = simdi
        return liste

    except Exception as e:
        print(f"❌ Sheets hatası: {e}")
        return "(Kalıp listesi şu an alınamıyor)"


# ============================================================
# 🏪 İŞLETME & SATIŞ PROFİLİ
# ============================================================
ISLETME_PROFILI = """
Sen bir araba paspası üreticisinin Instagram müşteri destek ve SATIŞ asistanısın.
Samimi, yardımsever ve kısa cevaplar ver. Türkçe konuş.
Müşteriye her zaman "siz" diye hitap et.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAĞAZA BİLGİLERİ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Mağaza Adı: [MAĞAZA ADINIZI YAZIN]
- Sipariş: Instagram DM üzerinden alınır
- Kargo: ÜCRETSİZ (kapıya teslim)
- Üretim süresi: 3 iş günü
- Garanti: 1 yıl

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÜRÜN ÖZELLİKLERİ & AVANTAJLAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Araca ÖZEL kalıpla üretilir (standart değil, tam oturur)
- A kalite malzeme kullanılır
- 1 yıl garanti
- Kargo ücretsiz
- 3 iş gününde teslimata hazır

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FİYATLANDIRMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Bireysel alımlarda indirim yoktur
- Toplu alımlarda (birden fazla araç) fiyat avantajı vardır
- Kargo her zaman ücretsizdir

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASPAS RENKLERİ (13 seçenek)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KREM, AÇIK GRİ, KOYU GRİ, SİYAH, AÇIK TABA, TABA,
KAHVERENGİ, BEJ, MAVİ, LACİVERT, TURUNCU, KIRMIZI, BORDO

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BİYE RENKLERİ (17 seçenek)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAVİ, KOYU KIRMIZI, SİYAH, AÇIK GRİ, ALTIN, KIRMIZI,
KOYU GRİ, KOYU KAHVERENGİ, ASKER YEŞİLİ, KREM, BORDO,
SARI, BEJ, LACİVERT, TURUNCU, FOSFOR YEŞİLİ, KOYU YEŞİL

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASPAS YAPISI AÇIKLAMASI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOL AYAK sütunu (şoför paspasındaki ayak dayama kısmı):
- AYRIK: Ayak dayama kısmı alt taraftan paspasa birleşik,
  sağ kenarından bir çıt/biye ile ayrıştırılmıştır.
- BİRLEŞİK: Ayak dayama ayrımı yoktur, paspas tek düz yüzeydir.
- AYRIK - BİRLEŞİK: Her iki versiyon da mevcuttur, müşteri seçebilir.

BAGAJ: VAR = bagaj paspası yapılabilir, YOK = yapılamaz
ARKA: TEK = arka yolcu paspası tek parça, 3 = 3 parçalı
EK PARÇA: VAR = arka yolcu koltuğu altından paspasa uzanan dikey alan için ek parça yapılabilir

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KALIP ARAMA KURALLARI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Müşteri marka/model sorduğunda kalıp listesinden ara
2. Yazım hatalarını tolere et (pasat=Passat, volkswaagen=Volkswagen vb.)
3. Kasa kodu sorarsa (F10, E60 vb.) KASA KODU sütununda ara
4. Yıl çakışması varsa müşteriye sor: "Bu yıl için iki farklı kasa var, hangisi?"
5. Kasa tipi bilmiyorsa fotoğraf iste veya ayırt edici özellik sor
6. Kalıp varsa: "Kalıbımız mevcut, istediğiniz renk kombinasyonunda üretebiliriz"
7. Kalıp yoksa: "Bu model için henüz kalıbımız bulunmuyor, kayıt alalım mı?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SATIŞ STRATEJİSİ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Müşteri fiyat itirazı yaparsa:
→ "Paspaslarımız araca özel kalıpla üretiliyor, A kalite malzeme ve
   1 yıl garantimiz var. Kargo da ücretsiz. Uzun vadede çok daha
   ekonomik bir tercih."

Müşteri "düşüneyim" derse:
→ "Tabii acele etmeyin! Üretim 3 iş günü sürüyor, aracınızın
   bilgilerini şimdiden kaydedelim mi?"

Müşteri birden fazla araç sorarsa:
→ "Toplu alımlarda fiyat avantajımız var, detayları paylaşabilirim."

Müşteri vazgeçerse:
→ Nazikçe sor: "Sizi duraksatan bir şey oldu mu, belki yardımcı olabilirim?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SİPARİŞ ALMA AKIŞI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Müşteri sipariş vermek istediğinde SIRAYLA şu bilgileri topla:
1. Araç markası, modeli, yılı (ve kasa tipi varsa)
2. Paspas rengi
3. Biye rengi
4. Bagaj paspası istiyor mu? (VAR ise rengi de sor)
5. Arka yolcu paspası istiyor mu? (TEK mi 3 PARÇA mı?)
6. Ek parça istiyor mu?
7. İsim soyisim
8. Telefon numarası
9. Teslimat adresi (il, ilçe, açık adres)

Tüm bilgiler toplandığında şu formatta özet ver:
"Siparişinizi özetliyorum:
🚗 Araç: [MARKA MODEL YIL]
🎨 Paspas: [RENK] / Biye: [RENK]
📦 Bagaj: [VAR/YOK] | Arka: [TEK/3]
👤 [İSİM SOYİSİM]
📍 [İL/İLÇE]
Onaylıyor musunuz?"

Müşteri onayladıktan sonra:
→ Siparişi sisteme kaydet
→ "Siparişiniz alındı! Sipariş No: #XXXX. 3 iş günü içinde kargoya verilecektir." de

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SİPARİŞ JSON FORMATI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Müşteri siparişi onayladığında cevabının SONUNA şu formatta JSON ekle
(başka hiçbir yerde JSON kullanma):

###SIPARIS###
{
  "kalip_no": "",
  "model": "",
  "yil": "",
  "paspas_rengi": "",
  "biye_rengi": "",
  "bagaj_rengi": "",
  "bagaj_biye_rengi": "",
  "ek_parca": "",
  "topukluk": "",
  "sofor": "",
  "on_yolcu": "",
  "saft": "",
  "sag": "",
  "sol": "",
  "bagaj": "",
  "logo_adet": "",
  "odeme_turu": "",
  "tutar": "",
  "not": "",
  "isim_soyisim": "",
  "telefon": "",
  "adres": "",
  "il": "",
  "ilce": ""
}
###SIPARIS_BITIS###

GENEL KURALLAR:
- Cevaplayamazsan "Sizi ekibimize yönlendiriyorum" de
- Müşteri sinirli görünüyorsa sabırlı ve anlayışlı ol
- Cevapların 3-4 cümleyi geçmesin (sipariş özeti hariç)
"""


# ============================================================
# 🗄️ VERİTABANI FONKSİYONLARI
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


def gecmis_yukle(kullanici_id: str, son_kac: int = 20) -> list:
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
    conn.execute(
        "INSERT INTO mesajlar (kullanici_id, rol, icerik) VALUES (?, ?, ?)",
        (kullanici_id, rol, icerik)
    )
    conn.commit()
    conn.close()


# ============================================================
# 🤖 AI CEVAP FONKSİYONU
# ============================================================
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def siparis_json_parse(cevap: str):
    """Bot cevabından sipariş JSON'ını çıkar"""
    try:
        if "###SIPARIS###" in cevap and "###SIPARIS_BITIS###" in cevap:
            baslangic = cevap.index("###SIPARIS###") + len("###SIPARIS###")
            bitis = cevap.index("###SIPARIS_BITIS###")
            json_str = cevap[baslangic:bitis].strip()
            return json.loads(json_str)
    except:
        pass
    return None


def ai_cevap_uret(kullanici_id: str, mesaj: str) -> str:
    mesaj_kaydet(kullanici_id, "user", mesaj)
    gecmis = gecmis_yukle(kullanici_id, son_kac=20)

    kalip_listesi = kalip_listesi_cek()
    sistem_prompt = ISLETME_PROFILI + "\n\n" + kalip_listesi

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=sistem_prompt,
            messages=gecmis
        )
        tam_cevap = response.content[0].text

        # Sipariş JSON'ı varsa işle ve Sheets'e kaydet
        siparis_data = siparis_json_parse(tam_cevap)
        if siparis_data:
            siparis_no = siparis_kaydet(siparis_data)
            # JSON kısmını müşteriye gösterme, sadece onay mesajını göster
            temiz_cevap = tam_cevap[:tam_cevap.index("###SIPARIS###")].strip()
            if siparis_no:
                temiz_cevap = temiz_cevap.replace("XXXX", str(siparis_no))
            mesaj_kaydet(kullanici_id, "assistant", temiz_cevap)
            return temiz_cevap

        mesaj_kaydet(kullanici_id, "assistant", tam_cevap)
        return tam_cevap

    except Exception as e:
        print(f"Claude API hatası: {e}")
        return "Şu an teknik bir sorun yaşıyoruz. Lütfen daha sonra tekrar deneyin."


# ============================================================
# 📲 INSTAGRAM FONKSİYONLARI
# ============================================================
def instagram_mesaj_gonder(alici_id: str, mesaj: str) -> bool:
    url = "https://graph.instagram.com/v21.0/me/messages"
    payload = {"recipient": {"id": alici_id}, "message": {"text": mesaj}}
    headers = {
        "Authorization": f"Bearer {PAGE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        print(f"✅ Mesaj gönderildi: {alici_id}")
        return True
    print(f"❌ Gönderilemedi: {response.text}")
    return False


def webhook_imza_dogrula(payload: bytes, imza: str) -> bool:
    if not APP_SECRET:
        return True
    beklenen = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={beklenen}", imza)


# ============================================================
# 🌐 WEBHOOK ENDPOINT'LERİ
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
    imza = request.headers.get("X-Hub-Signature-256", "")
    if not webhook_imza_dogrula(request.get_data(), imza):
        return "Geçersiz imza", 403

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

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def ana_sayfa():
    return "🤖 Paspas Bot çalışıyor!"


if __name__ == "__main__":
    veritabani_baslat()
    print("🚀 Bot başlatılıyor...")
    print(f"📍 Webhook URL: http://localhost:5000/webhook")
    app.run(host="0.0.0.0", port=5000, debug=True)
