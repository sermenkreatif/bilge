import anthropic, subprocess, threading, http.server, socketserver, json, time, re, queue, os, sys, signal
from datetime import datetime, timedelta

REPO="https://raw.githubusercontent.com/sermenkreatif/bilge/main"
DOSYALAR=["bilge_arayuz.html","bilge.py","bilge_sistem.txt","bilge_bilgi.txt"]

MIKROFON = False
DURUM = {"d":"hazir","duygu":"sakin","muzik":False,"muzik_ad":"","sahne":"yok","tema":"light","soz":"","panel":None,"video":None}
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
        s.wfile.write(json.dumps(DURUM).encode())
    def do_POST(s):
        n=int(s.headers.get("Content-Length",0))
        veri=s.rfile.read(n).decode("utf-8") if n else ""
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

client = anthropic.Anthropic()
ARAC = [{"type":"web_search_20250305","name":"web_search","max_uses":5}]
SISTEM = open("/home/ilhan/bilge_sistem.txt", encoding="utf-8").read()
try: SISTEM += "\n\n" + open("/home/ilhan/bilge_bilgi.txt", encoding="utf-8").read()
except: pass
SES = "tr-TR-EmelNeural"

_muzik={"p":None}
def baslik_temizle(b):
    b=re.sub(r'[\(\[\{][^)\]\}]*(?:official|video|audio|lyric|lyrics|visualizer|visualiser|remaster|remastered|4k|8k|hd|hq|full ?hd|mv|clip|klip|muzik|prod|explicit|sub|turkce|ceviri|color coded)[^)\]\}]*[\)\]\}]','',b,flags=re.IGNORECASE)
    b=re.sub(r'\s*[\-\|]\s*(?:official\s*)?(?:music\s*)?(?:video|audio|lyric\s*video|visualizer)\s*$','',b,flags=re.IGNORECASE)
    b=re.sub(r'\s{2,}',' ',b).strip(' -|\u00b7\u2014')
    return b or "Muzik"

def muzik_cal(arama):
    muzik_durdur()
    def _iste():
        try:
            cikti=subprocess.check_output(["yt-dlp","-f","bestaudio","-g","--get-title","ytsearch1:"+arama],
                  stderr=subprocess.DEVNULL,timeout=45).decode().strip().split("\n")
            baslik=baslik_temizle(cikti[0] if len(cikti)>=2 else arama)
            link=cikti[-1]
            if link.startswith("http"):
                _muzik["p"]=subprocess.Popen(["mpv","--no-terminal","--no-video","--ao=alsa","--audio-device=alsa/plughw:1,0",link],
                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                DURUM["muzik"]=True; DURUM["muzik_ad"]=baslik
        except: pass
    threading.Thread(target=_iste,daemon=True).start()
    return None
def muzik_durdur():
    if _muzik["p"] and _muzik["p"].poll() is None: _muzik["p"].terminate()
    _muzik["p"]=None; DURUM["muzik"]=False; DURUM["muzik_ad"]=""
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
            cikti=subprocess.check_output(["yt-dlp","--get-title","--get-id","ytsearch1:"+arama],
                  stderr=subprocess.DEVNULL,timeout=45).decode().strip().split("\n")
            if len(cikti)>=2:
                baslik=baslik_temizle(cikti[0]); vid=cikti[-1].strip()
                if vid: DURUM["video"]={"id":vid,"ad":baslik}
        except: pass
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
def konus(metin):
    metin=ses_metni(metin)
    if not metin: return
    DURUM["soz"]=metin[:220]
    DURUM["d"]="konusuyor"
    import edge_tts, asyncio
    async def _u(): await edge_tts.Communicate(metin, SES).save("/tmp/b.mp3")
    asyncio.run(_u())
    p=subprocess.Popen(["ffplay","-nodisp","-autoexit","-loglevel","quiet","/tmp/b.mp3"])
    _calan["p"]=p; p.wait(); _calan["p"]=None
    DURUM["d"]="hazir"
def sustur():
    if _calan["p"] and _calan["p"].poll() is None: _calan["p"].terminate()

def dusun_cevapla(soru, gecmis):
    DURUM["d"]="dusunuyor"
    gecmis.append({"role":"user","content":soru})
    while True:
        y=client.messages.create(model="claude-sonnet-4-6",max_tokens=800,
            system=SISTEM+" Bugunun tarihi: "+datetime.now().strftime("%d.%m.%Y")+" COK ONEMLI SON HATIRLATMA: Bu cevabin tamami bastan sona Turkce olacak. Tek bir Ingilizce kelime bile kullanma. Ingilizce dusunme, Turkce dusun ve Turkce yaz.",
            tools=ARAC,messages=gecmis)
        gecmis.append({"role":"assistant","content":y.content})
        if y.stop_reason=="pause_turn": continue
        break
    tam="".join(b.text for b in y.content if b.type=="text").strip()
    duygu="sakin"; sahne=None; tema=None; muzik_k=None; ses_k=None
    for anahtar in ["DUYGU","SAHNE","TEMA","MUZIK","SES","VOL","VOLUME","SOUND"]:
        while "["+anahtar+":" in tam:
            try:
                bas=tam.index("["+anahtar+":"); son=tam.index("]",bas)
                deger=tam[bas+len(anahtar)+2:son].strip()
                tam=(tam[:bas]+tam[son+1:]).strip()
                if anahtar=="DUYGU": duygu=deger
                elif anahtar=="SAHNE": sahne=deger
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
    global HATIRLATMALAR
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
        DURUM["duygu"]=duygu
        konus("Kendimi guncelliyorum, birazdan yeni halimle donerim.")
        kendini_guncelle()
        DURUM["reload"]=True; time.sleep(1)
        os.execv(sys.executable,[sys.executable]+sys.argv)
    if sahne is not None: DURUM["sahne"]=sahne
    if tema in ("light","dark"): DURUM["tema"]=tema
    DURUM["duygu"]=duygu
    tam=re.sub(r'\[[A-Za-zÇĞİÖŞÜçğıöşü]+(?::[^\]]*)?\]','',tam).strip()
    tam=re.sub(r'\s{2,}',' ',tam).strip()
    print("BILGE ["+duygu+"] (sahne="+str(sahne)+" tema="+str(tema)+"):", tam)
    if tam: konus(tam)
    # hava/atmosfer sahnesi SADECE o cevap icin gosterilir; konusma bitince kisa sure sonra kaybolur
    if sahne and sahne != "yok":
        threading.Timer(2.5, lambda: DURUM.__setitem__("sahne", "yok")).start()

def web_dinle(gecmis):
    while True:
        mesaj=_gelen.get()
        with _kilit:
            print("Sen (ekran):", mesaj)
            dusun_cevapla(mesaj, gecmis)
            if len(gecmis)>20: gecmis[:]=gecmis[-20:]

_site={"p":None}
def site_ac(url):
    url=url.strip()
    if not url.startswith("http"): url="https://"+url
    ortam=dict(os.environ); ortam["DISPLAY"]=":0"
    site_kapat()
    for komut in (["chromium","--user-data-dir=/tmp/bilge_site","--new-window","--start-fullscreen",url],
                  ["chromium-browser","--user-data-dir=/tmp/bilge_site","--new-window","--start-fullscreen",url],
                  ["xdg-open",url]):
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

def hatirlatma_kontrol():
    while True:
        time.sleep(30)
        simdi=datetime.now().strftime("%Y-%m-%d %H:%M")
        for h in HATIRLATMALAR:
            if h.get("bitti") or h.get("soylendi"): continue
            z=h.get("zaman","")
            if z and z<=simdi:
                with _kilit:
                    DURUM["panel"]={"baslik":"Hatirlatma","icerik":"- "+h["metin"]}
                    konus("Ilhan, hatirlatmam var: "+h["metin"])
                if h.get("tekrar"):
                    h["zaman"]=sonraki_zaman(h.get("saat","09:00"),h["tekrar"],h.get("gun"))
                    h["soylendi"]=False
                else:
                    h["soylendi"]=True
                hatirlatma_kaydet(HATIRLATMALAR)

def klavye_dongusu():
    print("BILGE hazir. Cikis: q")
    konus("Merhaba Ilhan, ben Bilge. Buyur, dinliyorum.")
    gecmis=[]
    threading.Thread(target=web_dinle,args=(gecmis,),daemon=True).start()
    threading.Thread(target=hatirlatma_kontrol,daemon=True).start()
    while True:
        soru=input("Sen: ")
        if soru=="q": break
        with _kilit:
            dusun_cevapla(soru, gecmis)
            if len(gecmis)>20: gecmis[:]=gecmis[-20:]

def mikrofon_dongusu():
    import numpy as np, sounddevice as sd
    from faster_whisper import WhisperModel
    print("Whisper yukleniyor..."); model=WhisperModel("small",device="cpu",compute_type="int8")
    SR=16000; ESIK=0.015; SESSIZLIK=1.0; gecmis=[]; konus("Merhaba Ilhan, seni dinliyorum.")
    threading.Thread(target=web_dinle,args=(gecmis,),daemon=True).start()
    q=[]
    def cb(i,f,t,s): q.append(i.copy())
    with sd.InputStream(samplerate=SR,channels=1,dtype="float32",blocksize=int(SR*0.1),callback=cb):
        while True:
            while True:
                if q:
                    bl=q.pop(0)
                    if float(np.sqrt(np.mean(bl**2)))>ESIK: sustur(); frames=[bl]; break
                else: time.sleep(0.02)
            sz=0
            while sz<int(SESSIZLIK/0.1):
                if q:
                    b=q.pop(0); frames.append(b)
                    sz=sz+1 if float(np.sqrt(np.mean(b**2)))<ESIK else 0
                else: time.sleep(0.02)
            DURUM["d"]="dusunuyor"; audio=np.concatenate(frames,axis=0)[:,0]
            segs,_=model.transcribe(audio,language="tr",beam_size=1)
            soru=" ".join(x.text.strip() for x in segs).strip()
            if len(soru)<2: DURUM["d"]="hazir"; continue
            with _kilit:
                print("Sen:", soru); dusun_cevapla(soru, gecmis)
                if len(gecmis)>20: gecmis[:]=gecmis[-20:]

if MIKROFON: mikrofon_dongusu()
else: klavye_dongusu()
