import anthropic, subprocess, threading, http.server, socketserver, json, time, re, queue, os, sys, signal, atexit
from datetime import datetime, timedelta

# Terminal locale UTF-8 olmasa bile Turkce karakter (u,i,s,c,g,o) input()'ta cokmesin
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import traceback
LOG_YOL="/home/ilhan/bilge.log"
def log(*a):
    satir="["+datetime.now().strftime("%H:%M:%S")+"] "+" ".join(str(x) for x in a)
    try:
        with open(LOG_YOL,"a",encoding="utf-8") as f: f.write(satir+"\n")
    except Exception: pass
    print(satir)

REPO="https://raw.githubusercontent.com/sermenkreatif/bilge/main"
DOSYALAR=["bilge_arayuz.html","bilge.py","bilge_sistem.txt","bilge_bilgi.txt"]

MIKROFON = True
TEST_MODU = bool(os.environ.get("BILGE_TEST"))  # yeni surumu izole dogrulamak icin

# ============ SES / KONUSMA MODU AYARLARI (Jabra gelince buradan ayarla) ============
# CIKIS cihazlari (BILGE'nin sesi + muzik). Projektor = plughw:1,0.
#   Senaryo A (varsayilan): ses+muzik projektorden, mikrofon Jabra'dan.
#   Senaryo B: BILGE'nin sesini de Jabra'dan vermek istersen -> aplay -l ile Jabra kartini bul,
#              TTS_CIHAZ'i ornek "alsa/plughw:2,0" yap (muzik projektorde kalabilir).
TTS_CIHAZ   = "alsa/plughw:2,0"    # BILGE konusma sesi (Jabra)
MUZIK_CIHAZ = "alsa/plughw:2,0"    # muzik (Jabra)
# GIRIS (mikrofon) cihazi. None = sistem varsayilani.
#   Jabra takilinca:  python3 -c "import sounddevice as sd; print(sd.query_devices())"
#   ciktisindan Jabra'yi gor; buraya index (sayi) YA DA ad parcasi ("Jabra") yaz.
MIK_CIHAZ   = 1       # Jabra Speak2 55 (sounddevice index)
# Wake word: BILGE sadece adi gecince cevap versin (TV/sohbet gurultusune tetiklenmesin)
WAKE_MODU   = True
WAKE        = ("bilge","bilgem","bilgeye","bilgen","bilgə")
WAKE_PENCERE= 15      # adi dedikten sonra bu kadar sn takip sorularinda wake gerekmez
MIK_MODEL   = "small" # "small"=daha dogru, "base"=daha hizli (Pi'de hiz icin base denenebilir)
MIK_ESIK    = 0.015   # ses algilama esigi (Jabra ile ayarlanir; dusuk=hassas, yuksek=sadece yakin ses)
DURUM = {"d":"hazir","muzik":False,"muzik_ad":"","sahne":"yok","tema":"light","panel":None,"video":None,"uyari":""}
_gelen = queue.Queue()
_kilit = threading.Lock()

class Sunucu(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
class H(http.server.BaseHTTPRequestHandler):
    def _cors(s):
        s.send_header("Access-Control-Allow-Origin","*")
        s.send_header("Access-Control-Allow-Headers","Content-Type")
    def do_OPTIONS(s):
        s.send_response(200); s._cors(); s.end_headers()
    def do_GET(s):
        s.send_response(200); s.send_header("Content-Type","application/json"); s._cors(); s.end_headers()
        s.wfile.write(json.dumps(dict(DURUM)).encode())
    def do_POST(s):
        n=int(s.headers.get("Content-Length",0))
        veri=s.rfile.read(n).decode("utf-8","ignore") if n else ""
        try:
            d=json.loads(veri); mesaj=d.get("mesaj","").strip()
            if d.get("panel_kapat"): DURUM["panel"]=None
            if d.get("video_kapat"): DURUM["video"]=None
        except: mesaj=""
        if mesaj: _gelen.put(mesaj)
        s.send_response(200); s.send_header("Content-Type","application/json"); s._cors(); s.end_headers()
        s.wfile.write(b'{"ok":true}')
    def log_message(s,*a): pass
def sunucu():
    with Sunucu(("0.0.0.0",8137),H) as sv: sv.serve_forever()
if not TEST_MODU:
    threading.Thread(target=sunucu,daemon=True).start()

HATIRLATMA_DOSYA="/home/ilhan/hatirlatmalar.json"
def hatirlatma_yukle():
    try:
        with open(HATIRLATMA_DOSYA,encoding="utf-8") as f: return json.load(f)
    except: return []
def hatirlatma_kaydet(liste):
    try:
        with open(HATIRLATMA_DOSYA,"w",encoding="utf-8") as f: json.dump(liste,f,ensure_ascii=False,indent=2)
    except: pass
HATIRLATMALAR=hatirlatma_yukle()
GUN_AD={"pazartesi":0,"pzt":0,"sali":1,"salı":1,"carsamba":2,"çarşamba":2,"crs":2,"persembe":3,"perşembe":3,"prs":3,"cuma":4,"cmrt":5,"cumartesi":5,"pazar":6,"paz":6}
def sonraki_zaman(saat, tekrar, gun=None):
    try: sa,dk=[int(x) for x in str(saat).split(":")]
    except: sa,dk=9,0
    now=datetime.now(); hedef=now.replace(hour=sa,minute=dk,second=0,microsecond=0)
    if tekrar=="gunluk":
        if hedef<=now: hedef+=timedelta(days=1)
    elif tekrar=="hafta_ici":
        if hedef<=now: hedef+=timedelta(days=1)
        while hedef.weekday()>=5: hedef+=timedelta(days=1)
    elif tekrar=="haftalik":
        g=gun if gun is not None else 0
        fark=(g-hedef.weekday())%7; hedef=hedef+timedelta(days=fark)
        if hedef<=now: hedef+=timedelta(days=7)
    return hedef.strftime("%Y-%m-%d %H:%M")
def liste_panele():
    aktif=[h for h in HATIRLATMALAR if not h.get("bitti")]
    if not aktif:
        DURUM["panel"]={"baslik":"Yapilacaklar","icerik":"Su an bekleyen bir sey yok."}; return
    sat=[]
    for h in aktif:
        if h.get("zaman"): sat.append("- "+h["zaman"]+" - "+h["metin"])
        else: sat.append("- "+h["metin"])
    DURUM["panel"]={"baslik":"Yapilacaklar ve Hatirlatmalar","icerik":"\n".join(sat)}

if not os.environ.get("ANTHROPIC_API_KEY"):
    print("HATA: ANTHROPIC_API_KEY tanimli degil. ~/.bashrc icine ekleyip 'source ~/.bashrc' calistir."); sys.exit(1)
client = anthropic.Anthropic()
ARAC = [{"type":"web_search_20250305","name":"web_search","max_uses":5}]
try:
    SISTEM = open("/home/ilhan/bilge_sistem.txt", encoding="utf-8").read()
except Exception as e:
    print("HATA: bilge_sistem.txt okunamadi:", e); sys.exit(1)
try: SISTEM += "\n\n" + open("/home/ilhan/bilge_bilgi.txt", encoding="utf-8").read()
except: pass
SES = "tr-TR-EmelNeural"

_muzik={"p":None}
_muzik_arama={"q":""}
def baslik_temizle(b):
    b=re.sub(r'[\(\[\{][^)\]\}]*(?:official|video|audio|lyric|lyrics|visualizer|visualiser|remaster|remastered|4k|8k|hd|hq|full ?hd|mv|clip|klip|muzik|prod|explicit|sub|turkce|ceviri|color coded)[^)\]\}]*[\)\]\}]','',b,flags=re.IGNORECASE)
    b=re.sub(r'\s*[\-\|]\s*(?:official\s*)?(?:music\s*)?(?:video|audio|lyric\s*video|visualizer)\s*$','',b,flags=re.IGNORECASE)
    b=re.sub(r'\s{2,}',' ',b).strip(' -|\u00b7\u2014')
    return b or "Muzik"

def muzik_cal(arama):
    muzik_durdur()
    _muzik_arama["q"]=arama
    def _iste():
        try:
            cikti=subprocess.check_output(["yt-dlp","-f","bestaudio","-g","--print","%(title)s","ytsearch1:"+arama],
                  stderr=subprocess.DEVNULL,timeout=60).decode("utf-8","ignore").strip().split("\n")
            cikti=[x for x in cikti if x.strip()]
            link=next((x for x in cikti if x.startswith("http")),"")
            baslik=baslik_temizle(next((x for x in cikti if not x.startswith("http")),arama))
            if link:
                # TTS card 1'i kullaniyorsa bitene kadar bekle (cakisma olmasin)
                bekle=0
                while _calan["p"] and _calan["p"].poll() is None and bekle<150:
                    time.sleep(0.1); bekle+=1
                logf=open("/tmp/mpv.log","w")
                _muzik["p"]=subprocess.Popen(["mpv","--no-terminal","--no-video","--audio-device="+MUZIK_CIHAZ,link],
                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=logf)
                DURUM["muzik"]=True; DURUM["muzik_ad"]=baslik; print("MUZIK caliyor:",baslik)
            else:
                print("MUZIK link yok:",repr(cikti))
        except Exception as e:
            print("MUZIK hata:",e)
    threading.Thread(target=_iste,daemon=True).start()
    return None
def muzik_durdur():
    if _muzik["p"] and _muzik["p"].poll() is None: _muzik["p"].terminate()
    _muzik["p"]=None; DURUM["muzik"]=False; DURUM["muzik_ad"]=""; _muzik_arama["q"]=""
def muzik_duraklat():
    if _muzik["p"] and _muzik["p"].poll() is None:
        try: os.kill(_muzik["p"].pid, signal.SIGSTOP); DURUM["muzik"]=False
        except: pass
def muzik_devam():
    if _muzik["p"] and _muzik["p"].poll() is None:
        try: os.kill(_muzik["p"].pid, signal.SIGCONT); DURUM["muzik"]=True
        except: pass

def video_bul(arama):
    muzik_durdur()
    def _iste():
        try:
            cikti=subprocess.check_output(
                  ["yt-dlp","--no-warnings","--print","%(title)s\n%(id)s","ytsearch1:"+arama],
                  stderr=subprocess.STDOUT,timeout=60).decode("utf-8","ignore").strip().split("\n")
            cikti=[x for x in cikti if x.strip()]
            if len(cikti)>=2:
                vid=cikti[-1].strip(); baslik=baslik_temizle(cikti[-2])
                if len(vid)>=8 and " " not in vid:
                    DURUM["video"]={"id":vid,"ad":baslik}; print("VIDEO bulundu:",vid,"|",baslik)
                else:
                    print("VIDEO id gecersiz:",repr(cikti))
            else:
                print("VIDEO sonuc yok:",repr(cikti))
        except Exception as e:
            print("VIDEO hata:",e)
    threading.Thread(target=_iste,daemon=True).start()
    return None

def kendini_guncelle():
    ok=True
    for f in DOSYALAR:
        try:
            subprocess.run(["wget","-q","-O","/home/ilhan/"+f,REPO+"/"+f],timeout=60,check=True)
        except: ok=False
    return ok

# --- Ses seviyesi kontrolu (hem BILGE sesi hem muzik ayni hoparlorden) ---
_ses={"seviye":80}
def _amixer(yuzde):
    for kart in ["-c","1"],[]:
        for kon in ["Master","PCM","Speaker","Headphone","DAC"]:
            try:
                subprocess.run(["amixer"]+kart+["sset",kon,str(yuzde)+"%"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            except: pass
def ses_ayarla(komut):
    k=str(komut).strip().upper()
    s=_ses["seviye"]
    if k=="SUS": s=0
    elif k=="KIS": s=max(0,s-25)
    elif k in ("AC","AÇ","YUKSELT","YÜKSELT"): s=min(100,s+25)
    else:
        try: s=max(0,min(100,int(re.sub(r'[^0-9]','',k))))
        except: return None
    _ses["seviye"]=s; _amixer(s); return s

# --- Sese giden metni insanlastir: markdown/baslik/liste isaretlerini temizle ---
def ses_metni(m):
    satirlar=[]
    for s in m.split("\n"):
        s=s.strip()
        if not s: continue
        s=re.sub(r'^#{1,6}\s*','',s)
        s=re.sub(r'^[-*\u2022]\s+','',s)
        s=re.sub(r'^\d+[\.\)]\s+','',s)
        s=s.rstrip(':')
        satirlar.append(s)
    t=" ".join(satirlar)
    t=t.replace("**","").replace("__","").replace("*","").replace("`","").replace("#","")
    t=re.sub(r'\s+',' ',t).strip()
    return t

_calan={"p":None}
_ses_kilit=threading.Lock()  # ayni anda tek TTS (hatirlatma/uyari/sohbet cakismasin)
def konus(metin):
    metin=ses_metni(metin)
    if not metin: return
    DURUM["d"]="konusuyor"
    # DUCKING: card 1 tek uygulamalik; konusurken muzigi durdur, sonra geri baslat
    _duck=None
    try:
        if _muzik["p"] and _muzik["p"].poll() is None:
            _duck=_muzik_arama["q"]
            try: _muzik["p"].terminate()
            except Exception: pass
            _muzik["p"]=None; DURUM["muzik"]=False
    except Exception: pass
    _ses_kilit.acquire()
    try:
        # --- 1) MP3 uret: once python edge_tts (her thread'de calisan loop), olmazsa edge-tts komutu ---
        uretildi=False
        try:
            import edge_tts, asyncio
            dongu=asyncio.new_event_loop()
            try:
                dongu.run_until_complete(edge_tts.Communicate(metin, SES).save("/tmp/b.mp3"))
            finally:
                dongu.close()
            uretildi=True
        except Exception as e1:
            try: log("TTS-uretim1 hata:", repr(e1))
            except Exception: pass
            try:
                subprocess.run(["edge-tts","--voice",SES,"--text",metin,"--write-media","/tmp/b.mp3"],
                               timeout=30, check=True)
                uretildi=True
            except Exception as e2:
                try: log("TTS-uretim2 hata:", repr(e2))
                except Exception: pass
        if not uretildi:
            DURUM["d"]="hazir"; return
        # --- 2) Cal: mpv ile dogrudan projektor kartina (card 1), olmazsa ffplay ---
        pr=None
        try:
            pr=subprocess.Popen(["mpv","--no-terminal","--audio-device="+TTS_CIHAZ,"/tmp/b.mp3"])
        except Exception as e3:
            try: log("TTS-cal1 hata:", repr(e3))
            except Exception: pass
            pr=subprocess.Popen(["ffplay","-nodisp","-autoexit","-loglevel","quiet","/tmp/b.mp3"])
        _calan["p"]=pr; pr.wait()
    except Exception as e:
        print("SES hata:", repr(e))
        try: log("SES hata:", repr(e))
        except Exception: pass
    finally:
        _ses_kilit.release()
        _calan["p"]=None; DURUM["d"]="hazir"
        if _duck:
            threading.Thread(target=lambda: muzik_cal(_duck), daemon=True).start()
def sustur():
    if _calan["p"] and _calan["p"].poll() is None: _calan["p"].terminate()

def dusun_cevapla(soru, gecmis):
    DURUM["d"]="dusunuyor"
    gecmis.append({"role":"user","content":soru})
    try:
        tur=0
        while True:
            y=client.messages.create(model="claude-sonnet-4-6",max_tokens=800,
                system=SISTEM+" Bugunun tarihi: "+datetime.now().strftime("%d.%m.%Y")+" HIZ KURALI: Sesli cevabin KISA olsun - normalde 1-2 cumle, en fazla 3. Uzun bilgi/liste gerekiyorsa kisaca ozetle ve detayi [PANEL]...[/PANEL] icine koy, sesli uzun uzun sayma. COK ONEMLI: Bu cevabin tamami bastan sona Turkce olacak. Tek bir Ingilizce kelime bile kullanma.",
                tools=ARAC,messages=gecmis)
            gecmis.append({"role":"assistant","content":y.content})
            tur+=1
            if y.stop_reason=="pause_turn" and tur<6: continue
            break
    except Exception as e:
        print("API hata:", e)
        if gecmis and gecmis[-1].get("role")=="user": gecmis.pop()
        DURUM["d"]="hazir"
        konus("Su an baglantida bir sorun var, birazdan tekrar dener misin?")
        return
    tam="".join(b.text for b in y.content if b.type=="text").strip()
    sahne=None; tema=None; muzik_k=None; ses_k=None
    for anahtar in ["SAHNE","TEMA","MUZIK","SES","VOL","VOLUME","SOUND"]:
        while "["+anahtar+":" in tam:
            try:
                bas=tam.index("["+anahtar+":"); son=tam.index("]",bas)
                deger=tam[bas+len(anahtar)+2:son].strip()
                tam=(tam[:bas]+tam[son+1:]).strip()
                if anahtar=="SAHNE": sahne=deger
                elif anahtar=="TEMA": tema=deger
                elif anahtar=="MUZIK": muzik_k=deger
                else: ses_k=deger
            except: break
    # PANEL: ekranda gosterilecek liste/detay blogu (seslendirilmez)
    if "[PANEL:KAPAT]" in tam:
        tam=tam.replace("[PANEL:KAPAT]","").strip(); DURUM["panel"]=None
    if "[PANEL]" in tam and "[/PANEL]" in tam:
        pb=tam.index("[PANEL]"); pe=tam.index("[/PANEL]")
        ham=tam[pb+7:pe].strip(); tam=(tam[:pb]+tam[pe+8:]).strip()
        sat=[x for x in ham.split("\n")]
        baslik=sat[0].strip() if sat else ""
        govde="\n".join(sat[1:]).strip() if len(sat)>1 else ""
        DURUM["panel"]={"baslik":baslik,"icerik":govde}
    # HATIRLATMA / GOREV / LISTE
    degisti=False
    while "[HATIRLAT:" in tam:
        try:
            b=tam.index("[HATIRLAT:"); e=tam.index("]",b); ic=tam[b+10:e]
            tam=(tam[:b]+tam[e+1:]).strip()
            if "|" in ic:
                z,m=ic.split("|",1); HATIRLATMALAR.append({"zaman":z.strip(),"metin":m.strip(),"bitti":False,"soylendi":False}); degisti=True
        except: break
    while "[GOREV:" in tam:
        try:
            b=tam.index("[GOREV:"); e=tam.index("]",b); m=tam[b+7:e].strip()
            tam=(tam[:b]+tam[e+1:]).strip()
            if m: HATIRLATMALAR.append({"zaman":"","metin":m,"bitti":False,"soylendi":True}); degisti=True
        except: break
    while "[DUZENLI:" in tam:
        try:
            b=tam.index("[DUZENLI:"); e=tam.index("]",b); ic=tam[b+9:e]
            tam=(tam[:b]+tam[e+1:]).strip()
            parca=ic.split("|")
            if len(parca)>=3:
                tipham=parca[0].strip().lower(); saat=parca[1].strip(); metin="|".join(parca[2:]).strip()
                gun=None; tip=tipham
                if tipham.startswith("haftalik"):
                    tip="haftalik"; tok=tipham.split()
                    if len(tok)>1: gun=GUN_AD.get(tok[1],0)
                if tip not in ("gunluk","hafta_ici","haftalik"): tip="gunluk"
                z=sonraki_zaman(saat,tip,gun)
                HATIRLATMALAR.append({"zaman":z,"metin":metin,"tekrar":tip,"gun":gun,"saat":saat,"bitti":False,"soylendi":False}); degisti=True
        except: break
    if degisti: hatirlatma_kaydet(HATIRLATMALAR)
    if "[LISTE]" in tam:
        tam=tam.replace("[LISTE]","").strip(); liste_panele()
    if "[KAPAT]" in tam:
        tam=tam.replace("[KAPAT]","").strip(); site_kapat(); DURUM["panel"]=None; DURUM["video"]=None
    while "[VIDEO:" in tam:
        try:
            b=tam.index("[VIDEO:"); e=tam.index("]",b); arg=tam[b+7:e].strip()
            tam=(tam[:b]+tam[e+1:]).strip()
            if arg.upper()=="KAPAT": DURUM["video"]=None
            elif arg: video_bul(arg)
        except: break
    while "[SITE:" in tam:
        try:
            b=tam.index("[SITE:"); e=tam.index("]",b); url=tam[b+6:e].strip()
            tam=(tam[:b]+tam[e+1:]).strip()
            if url: site_ac(url)
        except: break
    while "[OZETLE:" in tam:
        try:
            b=tam.index("[OZETLE:"); e=tam.index("]",b); url=tam[b+8:e].strip()
            tam=(tam[:b]+tam[e+1:]).strip()
            if url: site_ozetle(url)
        except: break
    if ses_k is not None: ses_ayarla(ses_k)
    if muzik_k is not None:
        u=muzik_k.upper()
        if u=="DUR": muzik_durdur()
        elif u in ("DURAKLAT","BEKLET","PAUSE"): muzik_duraklat()
        elif u in ("DEVAM","SURDUR","RESUME"): muzik_devam()
        else:
            ad=muzik_cal(muzik_k)
            if ad: tam=(tam+" Caliyorum: "+ad).strip()
    if "[GUNCELLE]" in tam:
        tam=tam.replace("[GUNCELLE]","").strip()
        konus("Kendimi guncelliyorum, birazdan yeni halimle donerim.")
        kendini_guncelle()
        DURUM["reload"]=True; time.sleep(1)
        os.execv(sys.executable,[sys.executable]+sys.argv)
    if sahne is not None: DURUM["sahne"]=sahne
    if tema in ("light","dark"): DURUM["tema"]=tema
    tam=re.sub(r'\[[A-Za-zÇĞİÖŞÜçğıöşü]+(?::[^\]]*)?\]','',tam).strip()
    tam=re.sub(r'\s{2,}',' ',tam).strip()
    print("BILGE (sahne="+str(sahne)+" tema="+str(tema)+"):", tam)
    if tam: konus(tam)
    # hava/atmosfer sahnesi SADECE o cevap icin gosterilir; konusma bitince kisa sure sonra kaybolur
    if sahne and sahne != "yok":
        threading.Timer(2.5, lambda: DURUM.__setitem__("sahne", "yok")).start()

def guvenli_cevapla(soru, gecmis):
    try:
        dusun_cevapla(soru, gecmis)
    except Exception as e:
        log("CEVAP hata:", e); log(traceback.format_exc()); DURUM["d"]="hazir"
    if len(gecmis)>20: gecmis[:]=gecmis[-20:]

# ===================== GELISTIRICI MODU (A - onayli) =====================
_oneri={"var":False,"ozet":""}
KAYNAK_YOL="/home/ilhan/bilge.py"
ONERI_YOL="/tmp/oneri_bilge.py"
IYI_YOL="/home/ilhan/bilge.py.iyi"
DEV_TETIK=("gelistirici mod","kendini duzelt","kendini gelistir","kendi kodunu","kod degisikligi","kendini guncelle kod")

def _dev_uret(istek):
    try:
        kaynak=open(KAYNAK_YOL,encoding="utf-8").read()
        y=client.messages.create(model="claude-sonnet-4-6",max_tokens=4000,
            system=("Sen BILGE adli Python programinin kaynak kodunu duzenleyen bir gelistiricisin. "
                    "Sana TAM kaynak kod ve bir degisiklik istegi verilecek. Gerekli EN KUCUK degisikligi yap. "
                    "Cevabini SADECE su formatta ver, baska hicbir sey yazma:\n"
                    "<<<ESKI\n(degistirilecek mevcut kod parcasi, dosyadan AYNEN, benzersiz olacak sekilde yeterince satir)\n>>>\n"
                    "<<<YENI\n(yerine gelecek yeni kod)\n>>>\n"
                    "<<<OZET\n(kullaniciya tek cumlelik Turkce ozet)\n>>>"),
            messages=[{"role":"user","content":"ISTEK: "+istek+"\n\nKAYNAK KOD:\n"+kaynak}])
        cev="".join(b.text for b in y.content if b.type=="text")
        import re as _re
        me=_re.search(r"<<<ESKI\n(.*?)\n>>>",cev,_re.S)
        my=_re.search(r"<<<YENI\n(.*?)\n>>>",cev,_re.S)
        mo=_re.search(r"<<<OZET\n(.*?)\n?>>>",cev,_re.S)
        if not(me and my):
            konus("Uygun bir degisiklik cikaramadim, isteni biraz daha netlestirir misin.")
            return
        eski=me.group(1); yeni=my.group(1); ozet=(mo.group(1).strip() if mo else "Kod degisikligi")
        if eski not in kaynak:
            konus("Degistirilecek yeri kaynakta tam bulamadim, tekrar dener misin."); return
        if kaynak.count(eski)!=1:
            konus("Degisiklik yeri benzersiz degil, daha net tarif et."); return
        yeni_kaynak=kaynak.replace(eski,yeni,1)
        # SOZDIZIMI KONTROLU
        import ast as _ast
        try: _ast.parse(yeni_kaynak)
        except Exception as e:
            konus("Onerdigim kod sozdizimi hatasi verdi, uygulamiyorum."); log("DEV sozdizimi hata:",repr(e)); return
        open(ONERI_YOL,"w",encoding="utf-8").write(yeni_kaynak)
        _oneri["var"]=True; _oneri["ozet"]=ozet
        with _kilit: DURUM["panel"]={"baslik":"Kod Degisikligi Onerisi","icerik":"- "+ozet+"\n- Onaylamak icin: 'uygula'\n- Vazgecmek icin: 'vazgec'"}
        konus("Degisikligi hazirladim. "+ozet+". Uygula dersen gecerim.")
    except Exception as e:
        log("DEV uret hata:",repr(e)); konus("Kod uzerinde calisirken hata oldu.")

def _dev_uygula():
    try:
        import shutil
        # GUVENLIK: yeni surumu ayri bir surecte GERCEKTEN calistirip dogrula
        # (sadece sozdizimi degil, import+init cokmesi de yakalanir)
        ortam=dict(os.environ); ortam["BILGE_TEST"]="1"
        try:
            r=subprocess.run([sys.executable, ONERI_YOL], env=ortam,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=40)
            cikti=r.stdout.decode("utf-8","ignore")
        except Exception as e:
            konus("Yeni surum testte takildi, uygulamiyorum."); log("DEV test istisna:",repr(e)); return
        if r.returncode!=0 or "TEST OK" not in cikti:
            konus("Yeni surum testi gecemedi, degisikligi uygulamiyorum, eski surum duruyor.")
            log("DEV test basarisiz: kod=",r.returncode," cikti=",cikti[-600:]); return
        shutil.copy(KAYNAK_YOL, IYI_YOL)         # calisan (test edilmis) surumu yedekle
        shutil.copy(ONERI_YOL, KAYNAK_YOL)       # yeni surumu yaz
        _oneri["var"]=False
        with _kilit: DURUM["panel"]=None
        konus("Test gecti, uyguluyorum. Yeni surumle birazdan geliyorum.")
        import time as _t; _t.sleep(3)
        os._exit(0)   # systemd yeni surumle yeniden baslatir
    except Exception as e:
        log("DEV uygula hata:",repr(e)); konus("Uygularken hata oldu, degisiklik gecmedi.")

def gelistirici_isle(mesaj):
    m=mesaj.lower().strip()
    if _oneri["var"]:
        if any(k in m for k in ("uygula","onayla","kabul et","evet uygula","gec")):
            _dev_uygula(); return True
        if any(k in m for k in ("vazgec","iptal","uygulama","gerek yok","dur")):
            _oneri["var"]=False
            try: os.remove(ONERI_YOL)
            except Exception: pass
            with _kilit: DURUM["panel"]=None
            konus("Tamam, degisiklikten vazgectim."); return True
    if any(t in m for t in DEV_TETIK):
        istek=mesaj
        threading.Thread(target=lambda: _dev_uret(istek),daemon=True).start()
        konus("Tamam, kodu inceliyorum.")
        return True
    return False
# =======================================================================

def web_dinle(gecmis):
    while True:
        mesaj=_gelen.get()
        with _kilit:
            print("Sen (ekran):", mesaj)
            if gelistirici_isle(mesaj): continue
            guvenli_cevapla(mesaj, gecmis)

_site={"p":None}
def site_ac(url):
    url=url.strip()
    if not url.startswith("http"): url="https://"+url
    ortam=dict(os.environ); ortam["DISPLAY"]=":0"
    site_kapat()
    # eski profil kilidini temizle (beyaz sayfa/acilmama sebebi)
    try: subprocess.run(["rm","-f","/tmp/bilge_site/SingletonLock","/tmp/bilge_site/SingletonSocket","/tmp/bilge_site/SingletonCookie"],timeout=5)
    except Exception: pass
    bayrak=["--user-data-dir=/tmp/bilge_site","--new-window","--start-fullscreen",
            "--no-first-run","--no-default-browser-check","--disable-session-crashed-bubble",
            "--disable-infobars","--disable-features=Translate","--autoplay-policy=no-user-gesture-required"]
    for komut in ([["chromium"]+bayrak+[url],
                  ["chromium-browser"]+bayrak+[url],
                  ["xdg-open",url]]):
        try:
            _site["p"]=subprocess.Popen(komut,env=ortam,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return True
        except: continue
    return False
def site_ozetle(url):
    def _iste():
        try:
            import urllib.request
            u=url.strip()
            if not u.startswith("http"): u="https://"+u
            req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"})
            ham=urllib.request.urlopen(req,timeout=20).read().decode("utf-8","ignore")
            metin=re.sub(r'(?is)<(script|style|noscript).*?</\1>',' ',ham)
            metin=re.sub(r'(?s)<[^>]+>',' ',metin)
            metin=re.sub(r'&[a-z#0-9]+;',' ',metin)
            metin=re.sub(r'\s+',' ',metin).strip()[:6000]
            if not metin: raise ValueError("bos")
            oz=client.messages.create(model="claude-sonnet-4-6",max_tokens=600,
                system="Sana bir web sayfasindan cikarilmis metin verilecek. TAMAMEN Turkce, kisa ve net ozetle. Cevabini SADECE su formatta ver: ilk satir kisa bir baslik, sonraki satirlar '- ' ile baslayan maddeler (en fazla 8 madde). Baska hicbir sey, hicbir aciklama yazma.",
                messages=[{"role":"user","content":"Sayfa: "+u+"\n\nMetin:\n"+metin}])
            cev="".join(b.text for b in oz.content if b.type=="text").strip()
            sat=[x for x in cev.split("\n") if x.strip()]
            baslik=sat[0].strip("-#* ").strip() if sat else "Ozet"
            govde="\n".join(sat[1:]).strip() if len(sat)>1 else cev
            with _kilit: DURUM["panel"]={"baslik":baslik,"icerik":govde}
        except:
            with _kilit: DURUM["panel"]={"baslik":"Ozet","icerik":"- Sayfaya ulasamadim ya da icerigi okuyamadim."}
    threading.Thread(target=_iste,daemon=True).start()
    return None
def site_kapat():
    if _site["p"] and _site["p"].poll() is None:
        try: _site["p"].terminate()
        except: pass
    _site["p"]=None
    try: subprocess.run(["pkill","-f","bilge_site"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
    except: pass

def temizle():
    for fn in (muzik_durdur, sustur, site_kapat):
        try: fn()
        except: pass
atexit.register(temizle)

def hatirlatma_kontrol():
    while True:
        time.sleep(30)
        simdi=datetime.now().strftime("%Y-%m-%d %H:%M")
        for h in HATIRLATMALAR:
            if h.get("bitti") or h.get("soylendi"): continue
            z=h.get("zaman","")
            if z and z<=simdi:
                try:
                    with _kilit:
                        DURUM["panel"]={"baslik":"Hatirlatma","icerik":"- "+h["metin"]}
                        konus("Ilhan, hatirlatmam var: "+h["metin"])
                    if h.get("tekrar"):
                        h["zaman"]=sonraki_zaman(h.get("saat","09:00"),h["tekrar"],h.get("gun"))
                        h["soylendi"]=False
                    else:
                        h["soylendi"]=True
                    hatirlatma_kaydet(HATIRLATMALAR)
                except Exception as e:
                    print("HATIRLATMA hata:", e)

def guc_izle():
    # dusuk voltaj / throttle / sicaklik izler, olunca ekrana+sese uyari verir
    son=""
    while True:
        try:
            ham=subprocess.check_output(["vcgencmd","get_throttled"],timeout=5).decode().strip()
            val=int(ham.split("=")[1],16)
            try: sic=subprocess.check_output(["vcgencmd","measure_temp"],timeout=5).decode().strip().split("=")[1]
            except Exception: sic="?"
            u=""
            if val & 0x1:   u="Guc dusuk (dusuk voltaj). Adaptoru kontrol et."
            elif val & 0x4: u="Islemci kisildi (throttle)."
            elif val & 0x8: u="Sicaklik yuksek: "+sic
            DURUM["uyari"]=u
            if u and u!=son:
                log("GUC UYARI:",u,ham,sic)
                try: konus(u)
                except Exception: pass
            son=u
        except Exception:
            pass
        time.sleep(20)

def klavye_dongusu():
    try: subprocess.run(["pkill","mpv"],timeout=5); subprocess.run(["pkill","ffplay"],timeout=5)
    except Exception: pass
    print("BILGE hazir. Cikis: q")
    konus("Merhaba Ilhan, ben Bilge. Buyur, dinliyorum.")
    gecmis=[]
    threading.Thread(target=web_dinle,args=(gecmis,),daemon=True).start()
    threading.Thread(target=hatirlatma_kontrol,daemon=True).start()
    threading.Thread(target=guc_izle,daemon=True).start()
    # servis/systemd olarak calisirken klavye (stdin) yoktur; beyni ayakta tut,
    # HTTP sunucu + sohbet kutusu + hatirlatmalar arka thread'lerde calismaya devam eder
    if not sys.stdin.isatty():
        while True: time.sleep(3600)
    while True:
        try:
            soru=input("Sen: ")
        except UnicodeDecodeError:
            print("(girdi cozulemedi, tekrar yaz)"); continue
        except EOFError:
            time.sleep(3600); continue
        if soru=="q": break
        with _kilit:
            if gelistirici_isle(soru): continue
            guvenli_cevapla(soru, gecmis)

def _mik_cihaz_bul():
    # MIK_CIHAZ: None=varsayilan, int=index, str=ad parcasi ("Jabra") ile eslesen giris
    if MIK_CIHAZ is None: return None
    try:
        import sounddevice as sd
        if isinstance(MIK_CIHAZ,int): return MIK_CIHAZ
        for i,d in enumerate(sd.query_devices()):
            if d.get("max_input_channels",0)>0 and str(MIK_CIHAZ).lower() in d.get("name","").lower():
                log("Mikrofon secildi:",i,d.get("name")); return i
        log("UYARI: MIK_CIHAZ bulunamadi, varsayilan kullanilacak:",MIK_CIHAZ)
    except Exception as e:
        log("Mik cihaz bul hata:",repr(e))
    return None

def mikrofon_dongusu():
    import numpy as np, sounddevice as sd
    from faster_whisper import WhisperModel
    print("Whisper yukleniyor ("+MIK_MODEL+")..."); model=WhisperModel(MIK_MODEL,device="cpu",compute_type="int8")
    SR=16000; ESIK=MIK_ESIK; SESSIZLIK=1.0; gecmis=[]
    cihaz=_mik_cihaz_bul()
    # hatirlatma + guc izleme thread'leri de bu modda calissin
    threading.Thread(target=web_dinle,args=(gecmis,),daemon=True).start()
    threading.Thread(target=hatirlatma_kontrol,daemon=True).start()
    threading.Thread(target=guc_izle,daemon=True).start()
    konus("Merhaba Ilhan, seni dinliyorum. Bana seslenmek icin adimi soyle: Bilge.")
    q=[]
    def cb(indata,frames_n,t,s): q.append(indata.copy())
    aktif_son=[0.0]  # son cevap zamani (wake penceresi)

    def _dinle_cumle():
        frames=None
        while True:
            # BILGE konusurken kendi sesini duyup tetiklenmesin: kuyrugu bosalt
            if _calan["p"] and _calan["p"].poll() is None:
                q.clear(); time.sleep(0.05); continue
            if q:
                bl=q.pop(0)
                if float(np.sqrt(np.mean(bl**2)))>ESIK: frames=[bl]; break
            else: time.sleep(0.02)
        sz=0
        while sz<int(SESSIZLIK/0.1):
            if q:
                b=q.pop(0); frames.append(b)
                sz=sz+1 if float(np.sqrt(np.mean(b**2)))<ESIK else 0
            else: time.sleep(0.02)
        return np.concatenate(frames,axis=0)[:,0]

    with sd.InputStream(samplerate=SR,channels=1,dtype="float32",device=cihaz,
                        blocksize=int(SR*0.1),callback=cb):
        while True:
            try:
                audio=_dinle_cumle()
                DURUM["d"]="dusunuyor"
                segs,_=model.transcribe(audio,language="tr",beam_size=1)
                metin=" ".join(x.text.strip() for x in segs).strip()
            except Exception as e:
                log("STT hata:",repr(e)); DURUM["d"]="hazir"; continue
            if len(metin)<2: DURUM["d"]="hazir"; continue
            dusuk=metin.lower()
            wake_var=any(w in dusuk for w in WAKE)
            pencere=(time.time()-aktif_son[0])<WAKE_PENCERE
            if WAKE_MODU and not wake_var and not pencere:
                DURUM["d"]="hazir"; print("(dinlendi, hitap yok):",metin); continue
            soru=metin
            if wake_var:
                for w in WAKE: soru=re.sub(r'(?i)'+re.escape(w),'',soru)
                soru=soru.strip(" ,.?!:;").strip()
            if not soru:
                aktif_son[0]=time.time(); konus("Efendim, dinliyorum."); DURUM["d"]="hazir"; continue
            print("Sen (ses):", soru)
            with _kilit:
                if gelistirici_isle(soru): aktif_son[0]=time.time(); continue
                guvenli_cevapla(soru, gecmis)
            aktif_son[0]=time.time()

if TEST_MODU:
    print("TEST OK"); sys.exit(0)
try:
    if MIKROFON: mikrofon_dongusu()
    else: klavye_dongusu()
except KeyboardInterrupt:
    pass
except Exception as _e:
    log("OLUMCUL HATA:", _e); log(traceback.format_exc()); time.sleep(2); raise
