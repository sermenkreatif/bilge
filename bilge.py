# -*- coding: utf-8 -*-
# ============================================================================
#  BILGE V1 - Ofis Ekip Sesli Asistani  (Raspberry Pi 5 + Jabra)
#  Zincir: Jabra -> Deepgram (STT) -> Claude -> edge-tts -> Jabra
#  Yerel AI yok -> Pi isinmaz. Tek dosya, bolumlere ayrilmis.
# ============================================================================
import os, sys, time, json, re, queue, threading, subprocess, traceback, io, wave
import urllib.request
from datetime import datetime, timedelta
import anthropic

# ============================ AYARLAR ========================================
KAYNAK_YOL   = "/home/ilhan/bilge.py"
IYI_YOL      = "/home/ilhan/bilge.py.iyi"
ONERI_YOL    = "/tmp/oneri_bilge.py"
SISTEM_YOL   = "/home/ilhan/bilge_sistem.txt"
BILGI_YOL    = "/home/ilhan/bilge_bilgi.txt"
LOG_YOL      = "/home/ilhan/bilge.log"
HATIRLATMA_YOL = "/home/ilhan/hatirlatmalar.json"

# --- Ses cihazlari (Jabra) ---
TTS_CIHAZ    = "alsa/plughw:2,0"   # BILGE'nin sesi (Jabra)
MUZIK_CIHAZ  = "alsa/plughw:2,0"   # muzik (Jabra)
MIK_CIHAZ    = 1                    # Jabra mikrofon (sounddevice index)
SES          = "tr-TR-EmelNeural"  # edge-tts Turkce kadin ses

# --- Konusma tanima (bulut STT: Deepgram) ---
DEEPGRAM_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
DG_MODEL     = "nova-2"
DG_DIL       = "tr"

# --- Wake word ---
WAKE_MODU    = True
WAKE         = ("bilge", "bilgem", "bilgeye", "bilgen", "bilgə", "bilge'",
                "bilgi", "belge", "bige", "bilher", "bilge'ye", "bilgeye", "pilge", "bilgü")
WAKE_PENCERE = 12   # C modu: wake sonrasi bu sure takip komutunda tekrar ad gerekmez      # adi dedikten sonra bu kadar sn takip sorularinda wake gerekmez
MIK_ESIK     = 0.02    # ses algilama esigi (Jabra sessiz=0.0013, konusma=0.04+)
SESSIZLIK    = 1.0     # bu kadar sn sessizlik olunca cumle bitti sayilir

TEST_MODU    = bool(os.environ.get("BILGE_TEST"))  # yeni surumu izole dogrulamak icin

# ============================ LOG + ZAMAN ====================================
def log(*a):
    s = "[" + datetime.now().strftime("%H:%M:%S") + "] " + " ".join(str(x) for x in a)
    try:
        with open(LOG_YOL, "a", encoding="utf-8") as f: f.write(s + "\n")
    except Exception: pass
    print(s)

_GUNLER = ["Pazartesi","Sali","Carsamba","Persembe","Cuma","Cumartesi","Pazar"]
def simdi_str():
    n = datetime.now()
    return n.strftime("%d.%m.%Y") + " " + _GUNLER[n.weekday()] + ", saat " + n.strftime("%H:%M")

# ============================ CLAUDE + SISTEM ================================
try:
    client = anthropic.Anthropic()
except Exception as e:
    log("Anthropic baslatilamadi:", repr(e)); sys.exit(1)

def _oku(yol, varsayilan=""):
    try:
        with open(yol, encoding="utf-8") as f: return f.read().strip()
    except Exception: return varsayilan

SISTEM = _oku(SISTEM_YOL, "Sen BILGE'sin, Turkce konusan bir asistan.")
BILGI  = _oku(BILGI_YOL, "")
if BILGI: SISTEM = SISTEM + "\n\n=== KURUMSAL BILGI ===\n" + BILGI

ARAC = [{"type": "web_search_20250305", "name": "web_search"}]

# ============================ DURUM (arayuz ile paylasilan) ==================
DURUM = {"d":"hazir", "muzik":False, "muzik_ad":"", "muzik_sanatci":"", "tema":"dark",
         "panel":None, "uyari":"",
         "sistem":{"cpu":0,"ram":0,"sicaklik":0,"depolama":0},
         "sohbet":[]}   # sohbet: son mesajlar [{"kim":"sen/bilge","metin":...,"saat":...}]
_kilit = threading.RLock()   # reentrant: ayni thread tekrar alabilir (deadlock onleme)
_gelen = queue.Queue()   # arayuz sohbet kutusundan gelen mesajlar
def sohbet_ekle(kim, metin):
    # NOT: _kilit ALMAZ - mesaj_isle zaten tutuyor olabilir (deadlock olmasin).
    # list.append CPython'da atomik, kilit gerekmez.
    try:
        DURUM["sohbet"].append({"kim":kim,"metin":metin[:400],"saat":datetime.now().strftime("%H:%M")})
        if len(DURUM["sohbet"])>20: del DURUM["sohbet"][:len(DURUM["sohbet"])-20]
    except Exception: pass

# ============================ HTTP SUNUCU (arayuz koprusu) ===================
import http.server, socketserver
class _Sunucu(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
class _H(http.server.BaseHTTPRequestHandler):
    def _cors(s):
        s.send_header("Access-Control-Allow-Origin", "*")
        s.send_header("Access-Control-Allow-Headers", "Content-Type")
    def do_OPTIONS(s):
        s.send_response(200); s._cors(); s.end_headers()
    def do_GET(s):
        s.send_response(200); s.send_header("Content-Type","application/json"); s._cors(); s.end_headers()
        s.wfile.write(json.dumps(DURUM).encode("utf-8"))
    def do_POST(s):
        n = int(s.headers.get("Content-Length", 0))
        veri = s.rfile.read(n).decode("utf-8","ignore") if n else ""
        try:
            d = json.loads(veri); mesaj = d.get("mesaj","").strip()
            if d.get("panel_kapat"):
                with _kilit: DURUM["panel"] = None
        except Exception: mesaj = ""
        if mesaj: _gelen.put(("ekran", mesaj))
        s.send_response(200); s.send_header("Content-Type","application/json"); s._cors(); s.end_headers()
        s.wfile.write(b'{"ok":true}')
    def log_message(s, *a): pass
def _sunucu_baslat():
    with _Sunucu(("0.0.0.0", 8137), _H) as sv: sv.serve_forever()
if not TEST_MODU:
    threading.Thread(target=_sunucu_baslat, daemon=True).start()

# ============================ SES: KONUSMA (edge-tts) ========================
_calan = {"p": None}
_ses_kilit = threading.RLock()   # reentrant: ayni thread tekrar alabilir (deadlock onleme)   # ayni anda tek konusma

def _ses_metni(m):
    # etiketleri ve panel bloklarini sesten temizle
    m = re.sub(r'\[PANEL\].*?\[/PANEL\]', ' ', m, flags=re.S)
    m = re.sub(r'\[[^\]]*\]', ' ', m)
    m = re.sub(r'\s+', ' ', m).strip()
    return m

def konus(metin):
    metin = _ses_metni(metin)
    if not metin: return
    sohbet_ekle("bilge", metin)
    # DUCKING: muzik calarken konusmak icin muzigi durdur, sonra geri baslat
    duck = None
    try:
        if _muzik["p"] and _muzik["p"].poll() is None:
            duck = _muzik["ad"]
            try: _muzik["p"].terminate()
            except Exception: pass
            _muzik["p"] = None
            with _kilit: DURUM["muzik"] = False
    except Exception: pass
    _ses_kilit.acquire()
    try:
        DURUM["d"] = "konusuyor"
        uretildi = False
        try:
            import edge_tts, asyncio
            dongu = asyncio.new_event_loop()
            try: dongu.run_until_complete(edge_tts.Communicate(metin, SES).save("/tmp/b.mp3"))
            finally: dongu.close()
            uretildi = True
        except Exception as e:
            log("TTS uretim hata:", repr(e))
        if uretildi:
            try:
                pr = subprocess.Popen(["mpv","--no-terminal","--audio-samplerate=48000",
                                       "--audio-device="+TTS_CIHAZ,"/tmp/b.mp3"])
            except Exception:
                pr = subprocess.Popen(["ffplay","-nodisp","-autoexit","-loglevel","quiet","/tmp/b.mp3"])
            _calan["p"] = pr; pr.wait()
    except Exception as e:
        log("SES hata:", repr(e))
    finally:
        _ses_kilit.release()
        _calan["p"] = None; DURUM["d"] = "hazir"
        if duck and not _muzik.get("kapali"):
            threading.Thread(target=lambda: muzik_cal(duck), daemon=True).start()

# ============================ SES: KONUSMA TANIMA (Deepgram) =================
def deepgram_yaz(audio_f32, sr=16000):
    # float32 sesi WAV'a cevir, Deepgram buluta yolla, Turkce yaziyi dondur
    import numpy as np
    pcm = (np.clip(audio_f32,-1,1)*32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf,"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
    url = ("https://api.deepgram.com/v1/listen?model="+DG_MODEL+
           "&language="+DG_DIL+"&punctuate=true&smart_format=true")
    req = urllib.request.Request(url, data=buf.getvalue(), method="POST")
    req.add_header("Authorization", "Token "+DEEPGRAM_KEY)
    req.add_header("Content-Type", "audio/wav")
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["results"]["channels"][0]["alternatives"][0]["transcript"].strip()

# ============================ MUZIK (YouTube) ================================
_muzik = {"p": None, "ad": "", "kapali": False}
def _baslik_ayikla(baslik):
    # YouTube basligindan "Sanatci - Sarki" cikar, gereksiz ekleri temizle
    b = baslik
    for ek in ["(Official Video)","(Official Music Video)","(Official Audio)","[Official Video]",
               "(Lyric Video)","(Lyrics)","(Video)","(Audio)","(Klip)","(Official)","(HD)","(4K)",
               "Official Video","Official Audio","Lyric Video","| Official","- Topic"]:
        b = re.sub(re.escape(ek), "", b, flags=re.I)
    b = re.sub(r'\s+', ' ', b).strip(" -|·").strip()
    if " - " in b:
        sanatci, sarki = b.split(" - ", 1)
        return sanatci.strip() + " — " + sarki.strip()
    return b

def muzik_cal(arama, video=False):
    _muzik["kapali"] = False
    def _iste():
        try:
            link = subprocess.run(["yt-dlp","-f","bestaudio" if not video else "best","-g","--no-playlist",
                                   "ytsearch1:"+arama], capture_output=True, text=True, timeout=30).stdout.strip()
            baslik = subprocess.run(["yt-dlp","--get-title","--no-playlist",
                                     "ytsearch1:"+arama], capture_output=True, text=True, timeout=30).stdout.strip()
            if not link: return
            try:
                if _muzik["p"] and _muzik["p"].poll() is None: _muzik["p"].terminate()
            except Exception: pass
            if video:
                ortam = dict(os.environ); ortam["DISPLAY"] = ":0"
                _muzik["p"] = subprocess.Popen(["mpv","--no-terminal","--fullscreen",
                                                "--input-ipc-server=/tmp/mpvsock",
                                                "--audio-device="+MUZIK_CIHAZ, link], env=ortam)
            else:
                _muzik["p"] = subprocess.Popen(["mpv","--no-terminal","--no-video",
                                                "--input-ipc-server=/tmp/mpvsock",
                                                "--audio-device="+MUZIK_CIHAZ, link])
            _muzik["ad"] = arama
            tam = _baslik_ayikla(baslik or arama)[:80]
            if " — " in tam: sanatci, sarki = tam.split(" — ",1)
            else: sanatci, sarki = "", tam
            with _kilit: DURUM["muzik"]=True; DURUM["muzik_ad"]=sarki.strip(); DURUM["muzik_sanatci"]=sanatci.strip()
        except Exception as e:
            log("Muzik hata:", repr(e))
    threading.Thread(target=_iste, daemon=True).start()

def muzik_ses(seviye):
    # calan muzigin sesini IPC ile ayarla (0-100). Muzigi durdurmaz, sadece kisar/acar.
    try:
        import socket, json as _j
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(0.5)
        s.connect("/tmp/mpvsock")
        s.send((_j.dumps({"command":["set_property","volume",seviye]})+"\n").encode())
        s.close(); return True
    except Exception:
        return False

def muzik_durdur():
    _muzik["kapali"] = True   # kullanici durdurdu -> ducking geri baslatmasin
    try:
        if _muzik["p"] and _muzik["p"].poll() is None:
            _muzik["p"].terminate()
            try: _muzik["p"].wait(timeout=1.5)   # cihazi tam biraksin
            except Exception:
                _muzik["p"].kill()
    except Exception: pass
    _muzik["p"] = None
    time.sleep(0.3)   # Jabra serbest kalsin, konusma bozulmasin
    with _kilit: DURUM["muzik"]=False; DURUM["muzik_ad"]=""; DURUM["muzik_sanatci"]=""

# ============================ SES SEVIYESI ==================================
def ses_ayarla(komut):
    try:
        if komut == "kapat":
            subprocess.run(["amixer","-c","2","sset","PCM","0%"], capture_output=True)
        elif komut == "artir":
            subprocess.run(["amixer","-c","2","sset","PCM","100%"], capture_output=True)
        elif komut == "azalt":
            subprocess.run(["amixer","-c","2","sset","PCM","50%"], capture_output=True)
    except Exception as e: log("Ses ayar hata:", repr(e))

# ============================ SITE ACMA =====================================
_site = {"p": None}
BILINEN_SITELER = {
    "youtube":"https://www.youtube.com","google":"https://www.google.com",
    "gmail":"https://mail.google.com","haber":"https://www.google.com/search?q=son+dakika+haberler",
    "hava":"https://www.google.com/search?q=hava+durumu+amasya",
    "amasya universitesi":"https://www.amasya.edu.tr","amasya üniversitesi":"https://www.amasya.edu.tr",
    "youtube muzik":"https://music.youtube.com","harita":"https://www.google.com/maps",
    "çeviri":"https://translate.google.com","ceviri":"https://translate.google.com",
    "wikipedia":"https://tr.wikipedia.org","eksi":"https://eksisozluk.com",
}
def _url_coz(metin):
    m = metin.strip().lower()
    for anahtar, url in BILINEN_SITELER.items():
        if anahtar in m: return url
    # adres gibi mi? (nokta iceriyor, bosluk yok) -> dogrudan
    if "." in metin and " " not in metin.strip():
        return metin if metin.startswith("http") else "https://"+metin.strip()
    # emin degil -> Google'da arat (yanlis adres acmaktansa)
    import urllib.parse
    return "https://www.google.com/search?q="+urllib.parse.quote(metin)

def site_ac(url):
    url = _url_coz(url)
    site_kapat()
    ortam = dict(os.environ); ortam["DISPLAY"] = ":0"
    try:
        _site["p"] = subprocess.Popen(["chromium","--user-data-dir=/tmp/bilge_site","--new-window",
            "--start-fullscreen","--no-first-run","--disable-session-crashed-bubble", url],
            env=ortam, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e: log("Site ac hata:", repr(e))
def site_kapat():
    try:
        if _site["p"] and _site["p"].poll() is None: _site["p"].terminate()
    except Exception: pass
    _site["p"] = None

# ============================ HATIRLATMA ====================================
def hatirlatma_yukle():
    try:
        with open(HATIRLATMA_YOL, encoding="utf-8") as f: return json.load(f)
    except Exception: return []
def hatirlatma_kaydet(liste):
    try:
        with open(HATIRLATMA_YOL,"w",encoding="utf-8") as f: json.dump(liste,f,ensure_ascii=False,indent=2)
    except Exception: pass
HATIRLATMALAR = hatirlatma_yukle()

def hatirlatma_ekle(saat, tekrar, mesaj):
    HATIRLATMALAR.append({"saat":saat,"tekrar":tekrar,"mesaj":mesaj,"son":""})
    hatirlatma_kaydet(HATIRLATMALAR)

def _sistem_oku():
    # CPU, RAM, sicaklik, depolama - Pi'den gercek degerler
    while True:
        try:
            # CPU: /proc/stat iki olcum farki
            def _cpu():
                def oku():
                    with open("/proc/stat") as f: p=f.readline().split()[1:8]
                    p=[int(x) for x in p]; return sum(p), p[3]  # toplam, idle
                t1,i1=oku(); time.sleep(0.3); t2,i2=oku()
                dt=t2-t1; di=i2-i1
                return round(100*(dt-di)/dt) if dt>0 else 0
            cpu=_cpu()
            # RAM
            mem={}
            with open("/proc/meminfo") as f:
                for ln in f:
                    k=ln.split(":"); 
                    if len(k)==2: mem[k[0]]=int(k[1].strip().split()[0])
            ram=round(100*(1-mem.get("MemAvailable",0)/mem.get("MemTotal",1)))
            # Sicaklik
            try:
                with open("/sys/class/thermal/thermal_zone0/temp") as f: sic=round(int(f.read())/1000)
            except Exception: sic=0
            # Depolama (kok)
            st=os.statvfs("/"); dep=round(100*(1-st.f_bavail/st.f_blocks))
            with _kilit:
                DURUM["sistem"]={"cpu":cpu,"ram":ram,"sicaklik":sic,"depolama":dep}
        except Exception as e:
            log("Sistem oku hata:", repr(e))
        time.sleep(3)

def hatirlatma_kontrol():
    while True:
        try:
            simdi = datetime.now().strftime("%H:%M")
            bugun = datetime.now().strftime("%Y-%m-%d")
            haftaici = datetime.now().weekday() < 5
            for h in HATIRLATMALAR:
                if h.get("saat") != simdi: continue
                if h.get("son") == bugun+" "+simdi: continue
                tk = h.get("tekrar","bir_kez")
                if tk == "hafta_ici" and not haftaici: continue
                h["son"] = bugun+" "+simdi; hatirlatma_kaydet(HATIRLATMALAR)
                konus("Hatirlatma: " + h.get("mesaj",""))
        except Exception as e: log("Hatirlatma hata:", repr(e))
        time.sleep(20)

# ============================ ETIKET ISLEME =================================
def etiket_isle(cevap):
    # cevaptaki [ETIKET:...] bloklarini isler; panel icerigini DURUM'a koyar
    # 1) PANEL
    mp = re.search(r'\[PANEL\](.*?)\[/PANEL\]', cevap, re.S)
    if mp:
        sat = [x.strip() for x in mp.group(1).strip().split("\n") if x.strip()]
        if sat:
            baslik = sat[0].strip("-* ").strip()
            govde = "\n".join(sat[1:]) if len(sat) > 1 else ""
            with _kilit: DURUM["panel"] = {"baslik":baslik, "icerik":govde}
    if "[PANEL:KAPAT]" in cevap:
        with _kilit: DURUM["panel"] = None
    # 2) MUZIK
    mm = re.search(r'\[MUZIK:(.*?)\]', cevap)
    if mm:
        arg = mm.group(1).strip()
        if arg.upper() == "DUR": muzik_durdur()
        else: muzik_cal(arg)
    mv = re.search(r'\[VIDEO:(.*?)\]', cevap)
    if mv:
        arg = mv.group(1).strip()
        if arg.upper() == "DUR": muzik_durdur()
        else: muzik_cal(arg, video=True)
    # 3) TEMA
    mt = re.search(r'\[TEMA:(.*?)\]', cevap)
    if mt:
        t = mt.group(1).strip().lower()
        with _kilit: DURUM["tema"] = "dark" if t in ("koyu","dark","karanlik") else "light"
    # 4) SES
    ms = re.search(r'\[SES:(.*?)\]', cevap)
    if ms: ses_ayarla(ms.group(1).strip().lower())
    # 5) SITE
    msi = re.search(r'\[SITE:(.*?)\]', cevap)
    if msi: site_ac(msi.group(1).strip())
    mara = re.search(r'\[ARA:(.*?)\]', cevap)
    if mara:
        import urllib.parse
        site_ac("https://www.google.com/search?q="+urllib.parse.quote(mara.group(1).strip()))
    # 6) HATIRLAT
    mh = re.search(r'\[HATIRLAT:(.*?)\]', cevap)
    if mh:
        try:
            p = dict(x.split("=",1) for x in mh.group(1).split("|") if "=" in x)
            hatirlatma_ekle(p.get("saat","09:00"), p.get("tekrar","bir_kez"), p.get("mesaj",""))
        except Exception as e: log("Hatirlat parse hata:", repr(e))
    # 7) KAPAT (topluca)
    if "[KAPAT]" in cevap:
        muzik_durdur(); site_kapat()
        with _kilit: DURUM["panel"] = None

# ============================ CLAUDE CEVAP ==================================
def dusun_cevapla(soru, gecmis):
    DURUM["d"] = "dusunuyor"
    gecmis.append({"role":"user","content":soru})
    # gecmisi kisa tut (hiz + ortak kullanim): son 8 mesaj
    if len(gecmis) > 8: del gecmis[:len(gecmis)-8]
    sistem = SISTEM + "\n\nSU AN: " + simdi_str() + ". Saat/tarih sorulursa bunu soyle, UTC deme."
    try:
        tur = 0
        while True:
            y = client.messages.create(model="claude-sonnet-4-6", max_tokens=700,
                    system=sistem, tools=ARAC, messages=gecmis)
            gecmis.append({"role":"assistant","content":y.content})
            tur += 1
            if y.stop_reason == "pause_turn" and tur < 4: continue
            break
        cevap = "".join(b.text for b in y.content if b.type == "text").strip()
    except Exception as e:
        log("Claude hata:", repr(e))
        if gecmis and gecmis[-1].get("role") == "user": gecmis.pop()
        DURUM["d"] = "hazir"
        konus("Baglantida bir sorun oldu, tekrar dener misin.")
        return
    etiket_isle(cevap)
    konus(cevap)

def guvenli_cevapla(soru, gecmis):
    try:
        dusun_cevapla(soru, gecmis)
    except Exception as e:
        log("Cevap hata:", repr(e)); log(traceback.format_exc())
        DURUM["d"] = "hazir"

# ============================ GELISTIRICI MODU (A - onayli) ==================
_oneri = {"var": False, "ozet": ""}
DEV_TETIK = ("gelistirici mod","kendini duzelt","kendini gelistir","kendi kodunu","kod degisikligi")

def _dev_uret(istek):
    try:
        kaynak = _oku(KAYNAK_YOL)
        y = client.messages.create(model="claude-sonnet-4-6", max_tokens=4000,
            system=("Sen BILGE adli Python programinin kaynagini duzenleyen gelistiricisin. "
                    "Sana TAM kaynak ve bir istek verilir. EN KUCUK degisikligi yap. "
                    "Cevabini SADECE su formatta ver:\n"
                    "<<<ESKI\n(dosyadan AYNEN, benzersiz kod parcasi)\n>>>\n"
                    "<<<YENI\n(yerine gelecek kod)\n>>>\n"
                    "<<<OZET\n(tek cumle Turkce ozet)\n>>>"),
            messages=[{"role":"user","content":"ISTEK: "+istek+"\n\nKAYNAK:\n"+kaynak}])
        cev = "".join(b.text for b in y.content if b.type == "text")
        me = re.search(r"<<<ESKI\n(.*?)\n>>>", cev, re.S)
        my = re.search(r"<<<YENI\n(.*?)\n>>>", cev, re.S)
        mo = re.search(r"<<<OZET\n(.*?)\n?>>>", cev, re.S)
        if not (me and my):
            konus("Uygun bir degisiklik cikaramadim, isteni netlestir."); return
        eski, yeni = me.group(1), my.group(1)
        ozet = mo.group(1).strip() if mo else "Kod degisikligi"
        if kaynak.count(eski) != 1:
            konus("Degisiklik yerini benzersiz bulamadim, tekrar dene."); return
        yeni_kaynak = kaynak.replace(eski, yeni, 1)
        import ast
        try: ast.parse(yeni_kaynak)
        except Exception as e:
            konus("Onerdigim kod sozdizimi hatasi verdi, uygulamiyorum."); log("DEV sozdizimi:", repr(e)); return
        open(ONERI_YOL,"w",encoding="utf-8").write(yeni_kaynak)
        _oneri["var"] = True; _oneri["ozet"] = ozet
        with _kilit: DURUM["panel"] = {"baslik":"Kod Degisikligi Onerisi",
                                       "icerik":"- "+ozet+"\n- Uygulamak: 'uygula'\n- Vazgecmek: 'vazgec'"}
        konus("Degisikligi hazirladim. " + ozet + ". Uygula dersen gecerim.")
    except Exception as e:
        log("DEV uret hata:", repr(e)); konus("Kod uzerinde calisirken hata oldu.")

def _dev_uygula():
    try:
        import shutil
        ortam = dict(os.environ); ortam["BILGE_TEST"] = "1"
        try:
            r = subprocess.run([sys.executable, ONERI_YOL], env=ortam,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40)
            cikti = r.stdout.decode("utf-8","ignore")
        except Exception as e:
            konus("Yeni surum testte takildi, uygulamiyorum."); log("DEV test:", repr(e)); return
        if r.returncode != 0 or "TEST OK" not in cikti:
            konus("Yeni surum testi gecemedi, eski surum duruyor."); log("DEV test basarisiz:", cikti[-400:]); return
        shutil.copy(KAYNAK_YOL, IYI_YOL)
        shutil.copy(ONERI_YOL, KAYNAK_YOL)
        _oneri["var"] = False
        with _kilit: DURUM["panel"] = None
        konus("Test gecti, uyguluyorum. Yeni surumle geliyorum.")
        time.sleep(2); os._exit(0)   # systemd yeni surumle baslatir
    except Exception as e:
        log("DEV uygula hata:", repr(e)); konus("Uygularken hata oldu, degisiklik gecmedi.")

def gelistirici_isle(mesaj):
    m = mesaj.lower().strip()
    if _oneri["var"]:
        if any(k in m for k in ("uygula","onayla","kabul","evet uygula")):
            _dev_uygula(); return True
        if any(k in m for k in ("vazgec","iptal","gerek yok","uygulama")):
            _oneri["var"] = False
            try: os.remove(ONERI_YOL)
            except Exception: pass
            with _kilit: DURUM["panel"] = None
            konus("Tamam, vazgectim."); return True
    if any(t in m for t in DEV_TETIK):
        threading.Thread(target=lambda: _dev_uret(mesaj), daemon=True).start()
        konus("Tamam, kodu inceliyorum.")
        return True
    return False

# ============================ MESAJ ISLEME (ortak) ==========================
def mesaj_isle(soru, gecmis):
    sohbet_ekle("sen", soru)
    with _kilit:
        if gelistirici_isle(soru): return
        guvenli_cevapla(soru, gecmis)

# ============================ ARAYUZ SOHBET KUTUSU ==========================
def ekran_dinle(gecmis):
    while True:
        try:
            kaynak, mesaj = _gelen.get()
            log("Sen (ekran):", mesaj)
            mesaj_isle(mesaj, gecmis)
        except Exception as e: log("Ekran dinle hata:", repr(e))

# ============================ KONUSMA DONGUSU (Jabra + wake) =================
def _mik_index():
    if MIK_CIHAZ is None: return None
    try:
        import sounddevice as sd
        if isinstance(MIK_CIHAZ, int): return MIK_CIHAZ
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels",0) > 0 and str(MIK_CIHAZ).lower() in d.get("name","").lower():
                return i
    except Exception as e: log("Mik index hata:", repr(e))
    return None

def konusma_dongusu(gecmis):
    import numpy as np, sounddevice as sd
    if not DEEPGRAM_KEY:
        log("UYARI: DEEPGRAM_API_KEY yok - konusma tanima calismaz.")
    SR = 16000
    cihaz = _mik_index()
    q = []
    def cb(indata, frames, t, s): q.append(indata.copy())
    aktif_son = [0.0]

    def _cumle_dinle():
        frames = None
        while True:
            if _calan["p"] and _calan["p"].poll() is None:   # BILGE konusurken dinleme (kendini duymasin)
                q.clear(); time.sleep(0.05); continue
            if q:
                bl = q.pop(0)
                if float(np.sqrt(np.mean(bl**2))) > MIK_ESIK: frames = [bl]; break
            else: time.sleep(0.02)
        sz = 0
        while sz < int(SESSIZLIK/0.1):
            if q:
                b = q.pop(0); frames.append(b)
                sz = sz+1 if float(np.sqrt(np.mean(b**2))) < MIK_ESIK else 0
            else: time.sleep(0.02)
        return np.concatenate(frames, axis=0)[:,0]

    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=cihaz,
                        blocksize=int(SR*0.1), callback=cb):
        while True:
            try:
                audio = _cumle_dinle()
                DURUM["d"] = "dusunuyor"
                metin = deepgram_yaz(audio, SR)
            except Exception as e:
                log("STT hata:", repr(e)); DURUM["d"] = "hazir"; continue
            if len(metin) < 2: DURUM["d"] = "hazir"; continue
            dusuk = metin.lower().strip()
            WAKE_KESIN = ("bilge","bilgem","bilgeye","bilgen","bilgə","bilge'","bilge'ye","bilgü")
            WAKE_BAS = ("bilgi","belge","bige","bilher","pilge")  # sadece cumle basinda
            wake = any(w in dusuk for w in WAKE_KESIN) or any(dusuk.startswith(w) for w in WAKE_BAS)
            pencere = (time.time() - aktif_son[0]) < WAKE_PENCERE
            if WAKE_MODU and not wake and not pencere:
                DURUM["d"] = "hazir"; log("(hitap yok):", metin); continue
            # A: wake duyuldu -> muzik calıyorsa sesini kıs (komutu net duy)
            muzik_kisildi = False
            if wake and _muzik["p"] and _muzik["p"].poll() is None:
                if muzik_ses(25): muzik_kisildi = True
            soru = metin
            if wake:
                for w in WAKE_KESIN: soru = re.sub(r'(?i)'+re.escape(w), '', soru)
                for w in WAKE_BAS: soru = re.sub(r'(?i)^'+re.escape(w), '', soru.strip())
                soru = soru.strip(" ,.?!:;").strip()
            if not soru:
                aktif_son[0] = time.time(); konus("Efendim?"); DURUM["d"] = "hazir"
                if muzik_kisildi and _muzik["p"] and _muzik["p"].poll() is None: muzik_ses(100)
                continue
            log("Sen (ses):", soru)
            mesaj_isle(soru, gecmis)
            aktif_son[0] = time.time()
            # muzik hala calıyorsa (durdurulmadıysa) sesi geri ac
            if muzik_kisildi and _muzik["p"] and _muzik["p"].poll() is None:
                time.sleep(0.3); muzik_ses(100)

# ============================ ANA ===========================================
if TEST_MODU:
    print("TEST OK"); sys.exit(0)

def main():
    gecmis = []
    threading.Thread(target=ekran_dinle, args=(gecmis,), daemon=True).start()
    threading.Thread(target=hatirlatma_kontrol, daemon=True).start()
    threading.Thread(target=_sistem_oku, daemon=True).start()
    konus("Merhaba, ben Bilge. Nasil yardimci olabilirim?")
    try:
        konusma_dongusu(gecmis)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log("OLUMCUL HATA:", repr(e)); log(traceback.format_exc()); time.sleep(2); raise

if __name__ == "__main__":
    main()
