"""
7OwO7 Poketool
----------------
Drag&Drop -> drehen (fliesst ins finale Bild ein) -> freistellen ->
OCR + automatischer Karten-Lookup -> Zertifikats-Pruefung (PSA/CGC) ->
pricecharting-Preise (USD+EUR) -> Verkaufstext -> Download-Auswahl.

Starten:  pip install -r requirements.txt  &&  streamlit run app.py
"""

import base64
import io
import os

import numpy as np
import streamlit as st
from PIL import Image

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    from streamlit_cropper import st_cropper
    CROPPER_AVAILABLE = True
except ImportError:
    CROPPER_AVAILABLE = False

from crop_utils import crop_card_or_slab
from recognition import recognize_card
from card_lookup import lookup_by_number, lookup_by_name
from cert_lookup import lookup_cert, supports_auto_lookup, cert_url
from psa_api import lookup_psa_cert, load_saved_token, save_token, can_pull_today, last_pull_today
from pricecharting import (
    search_candidates, get_prices_for_url, get_usd_eur_rate, usd_string_to_eur,
)
from sales_text import generate_sales_text

st.set_page_config(page_title="7OwO7 Pokétool", page_icon="🔴", layout="wide")


def inject_style(max_width_px: int):
    video_html = ""
    video_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "background.mp4")
    if os.path.exists(video_path) and os.path.getsize(video_path) < 30 * 1024 * 1024:
        with open(video_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        video_html = f"""
        <video autoplay muted loop playsinline
               style="position:fixed;top:0;left:0;width:100vw;height:100vh;
                      object-fit:cover;z-index:-2;opacity:0.18;pointer-events:none;">
          <source src="data:video/mp4;base64,{b64}" type="video/mp4">
        </video>"""

    # Pokeball-Outline als SVG-Muster fuer den Hintergrund (eigene Grafik)
    pokeball_pattern = (
        "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='140' height='140' viewBox='0 0 140 140'%3E%3Cg fill='none' "
        "stroke='%23ffffff' stroke-width='3'%3E%3Ccircle cx='70' cy='70' r='36'/%3E"
        "%3Cpath d='M34 70h26M80 70h26'/%3E%3Ccircle cx='70' cy='70' r='11'/%3E"
        "%3C/g%3E%3C/svg%3E\")"
    )

    css = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;700;800&family=Nunito:wght@400;600;700&family=Press+Start+2P&display=swap');

    :root {
        --dex-red: #E3350D;
        --ball-yellow: #FFCB05;
        --cerulean: #2A75BB;
        --navy: #0D1220;
        --navy-2: #141A2E;
        --panel: #1A2138;
        --panel-edge: #2A3355;
        --slab: #F2F0EA;
        --ink: #151A2C;
        --text: #E8EAF2;
        --muted: #8B96BC;
    }

    /* ---------- Grundgeruest ---------- */
    .block-container {
        max-width: __MAXW__px !important;
        margin-left:auto !important; margin-right:auto !important;
        padding-left:2rem !important; padding-right:2rem !important;
    }
    .stImage img { max-height:70vh; object-fit:contain;
        border-radius:12px; }

    .stApp {
        background:
            radial-gradient(1100px 560px at 75% -8%, rgba(42,117,187,.22), transparent 60%),
            radial-gradient(900px 520px at 8% 108%, rgba(227,53,13,.16), transparent 60%),
            var(--navy);
        font-family:'Nunito', sans-serif;
    }
    .stApp::before {
        content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
        background-image: __PATTERN__;
        opacity:.05;
        animation: patternDrift 90s linear infinite;
    }
    @keyframes patternDrift {
        from { background-position: 0 0; }
        to   { background-position: 280px 280px; }
    }

    p, label, .stMarkdown, .stCaption { color: var(--text); }
    [data-testid="stCaptionContainer"] { color: var(--muted); }

    /* ---------- Pokedex-Header ---------- */
    .dex-bar {
        display:flex; align-items:center; gap:1.1rem;
        background: linear-gradient(180deg, #f04329 0%, var(--dex-red) 55%, #b52708 100%);
        border-radius: 18px 18px 22px 22px;
        padding: .9rem 1.4rem;
        margin-bottom: 1.4rem;
        box-shadow: 0 10px 30px rgba(227,53,13,.28),
                    inset 0 2px 0 rgba(255,255,255,.28),
                    inset 0 -4px 0 rgba(0,0,0,.22);
        position:relative; overflow:hidden;
    }
    .dex-bar::after { /* diagonale Gehaeuse-Kante rechts */
        content:""; position:absolute; right:-30px; top:-20px;
        width:130px; height:200%;
        background: rgba(255,255,255,.07); transform: rotate(18deg);
        pointer-events:none;
    }
    .dex-lens {
        width:52px; height:52px; border-radius:50%; flex:0 0 auto;
        background: radial-gradient(circle at 34% 30%, #d9f1ff 0%, #7fc4f4 22%, var(--cerulean) 58%, #123152 100%);
        border: 4px solid #f6f4ee;
        box-shadow: 0 0 0 3px #1a1a1a, 0 4px 10px rgba(0,0,0,.35),
                    inset 0 -4px 8px rgba(0,0,0,.35);
        position:relative;
        animation: lensPulse 5s ease-in-out infinite;
    }
    .dex-lens::after {
        content:""; position:absolute; top:8px; left:10px;
        width:12px; height:8px; border-radius:50%;
        background: rgba(255,255,255,.85); transform: rotate(-20deg);
    }
    @keyframes lensPulse {
        0%,100% { box-shadow: 0 0 0 3px #1a1a1a, 0 4px 10px rgba(0,0,0,.35), inset 0 -4px 8px rgba(0,0,0,.35); }
        50%     { box-shadow: 0 0 0 3px #1a1a1a, 0 4px 18px rgba(42,117,187,.65), inset 0 -4px 8px rgba(0,0,0,.35); }
    }
    .dex-leds { display:flex; flex-direction:column; gap:6px; flex:0 0 auto; }
    .led {
        width:11px; height:11px; border-radius:50%;
        border: 2px solid rgba(0,0,0,.45);
        box-shadow: inset 0 -2px 3px rgba(0,0,0,.35);
    }
    .led-r { background:#ff6b52; animation: ledBlink 2.4s ease-in-out infinite; }
    .led-y { background:var(--ball-yellow); animation: ledBlink 2.4s ease-in-out .8s infinite; }
    .led-g { background:#4be08a; animation: ledBlink 2.4s ease-in-out 1.6s infinite; }
    @keyframes ledBlink {
        0%,100% { filter:brightness(.75); } 50% { filter:brightness(1.5); }
    }
    .dex-title-wrap { display:flex; flex-direction:column; gap:2px; min-width:0; }
    .poketool-title {
        font-family:'Baloo 2', sans-serif;
        font-size: 2.4rem; font-weight:800; line-height:1.05;
        letter-spacing:.5px;
        background: linear-gradient(100deg,
            #FFF7C2 0%, var(--ball-yellow) 18%, #FF8A5C 38%,
            #FF3BD4 55%, #37C8FF 72%, #FFF7C2 100%);
        background-size: 260% 100%;
        -webkit-background-clip:text; background-clip:text;
        -webkit-text-fill-color:transparent;
        animation: holoSheen 7s linear infinite;
        text-shadow: 0 2px 12px rgba(0,0,0,.001); /* fix fuer clip-Rendering */
    }
    @keyframes holoSheen {
        from { background-position: 0% 50%; }
        to   { background-position: 260% 50%; }
    }
    .dex-tagline {
        font-family:'Press Start 2P', monospace;
        font-size: 8.5px; letter-spacing: 2.5px;
        color: rgba(255,244,230,.85);
        text-shadow: 0 1px 0 rgba(0,0,0,.35);
    }
    .dex-ball {
        margin-left:auto; flex:0 0 auto;
        width:44px; height:44px; border-radius:50%;
        background: linear-gradient(to bottom, #ff5a43 0 44%, #1a1a1a 44% 56%, #f5f5f5 56% 100%);
        border:3px solid #1a1a1a; position:relative;
        transition: transform .5s cubic-bezier(.2,1.6,.4,1);
        cursor:default;
    }
    .dex-ball::after {
        content:""; position:absolute; top:50%; left:50%;
        width:12px; height:12px; border-radius:50%;
        background:#f5f5f5; border:3px solid #1a1a1a;
        transform: translate(-50%,-50%);
    }
    .dex-bar:hover .dex-ball { transform: rotate(360deg); }

    /* ---------- Slab-Label als Karten-Ueberschrift ---------- */
    .block-container h3 {
        display:inline-block;
        font-family:'Baloo 2', sans-serif; font-weight:700;
        color: var(--ink) !important;
        background: linear-gradient(180deg, #FBFAF6 0%, var(--slab) 60%, #DEDACB 100%);
        border-left: 12px solid var(--dex-red);
        border-radius: 8px;
        padding: .4rem 1.2rem .45rem 1rem;
        box-shadow: 0 3px 10px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.8);
        letter-spacing:.3px;
    }

    /* ---------- Buttons ---------- */
    .stButton > button, .stDownloadButton > button {
        font-family:'Baloo 2', sans-serif; font-weight:700;
        border-radius: 999px;
        border: 2px solid var(--panel-edge);
        background: linear-gradient(180deg, #232C4D 0%, var(--panel) 100%);
        color: var(--text);
        padding: .45rem 1.15rem;
        box-shadow: 0 3px 0 rgba(0,0,0,.4);
        transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        border-color: var(--ball-yellow);
        color: #FFF3C4;
        transform: translateY(-2px);
        box-shadow: 0 5px 0 rgba(0,0,0,.4), 0 0 18px rgba(255,203,5,.25);
    }
    .stButton > button:active, .stDownloadButton > button:active {
        transform: translateY(1px);
        box-shadow: 0 1px 0 rgba(0,0,0,.4);
    }

    /* ---------- Eingaben ---------- */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input {
        background: #10162B !important;
        border: 1.5px solid var(--panel-edge) !important;
        border-radius: 10px !important;
        color: var(--text) !important;
        transition: border-color .15s ease, box-shadow .15s ease;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus {
        border-color: var(--ball-yellow) !important;
        box-shadow: 0 0 0 3px rgba(255,203,5,.18) !important;
    }
    [data-testid="stSelectbox"] > div > div {
        background: #10162B !important;
        border: 1.5px solid var(--panel-edge) !important;
        border-radius: 10px !important;
        color: var(--text) !important;
    }

    /* ---------- Datei-Uploader = Binder-Tasche ---------- */
    [data-testid="stFileUploader"] section {
        background: linear-gradient(180deg, rgba(42,117,187,.10), rgba(255,255,255,.02));
        border: 2px dashed rgba(255,203,5,.5);
        border-radius: 16px;
        transition: border-color .2s ease, background .2s ease, transform .2s ease;
    }
    [data-testid="stFileUploader"] section:hover {
        border-color: var(--ball-yellow);
        background: linear-gradient(180deg, rgba(42,117,187,.18), rgba(255,255,255,.04));
        transform: translateY(-1px);
    }

    /* ---------- Expander & Alerts & Tabellen ---------- */
    [data-testid="stExpander"] {
        background: rgba(255,255,255,.03);
        border: 1px solid var(--panel-edge);
        border-radius: 12px;
        overflow:hidden;
    }
    [data-testid="stAlert"] {
        border-radius: 12px;
        border-left: 6px solid var(--ball-yellow);
    }
    [data-testid="stTable"] {
        background: rgba(255,255,255,.03);
        border-radius: 12px;
    }

    /* ---------- Divider mit Pokeball-Mitte ---------- */
    .block-container hr {
        border: none; height: 26px; position: relative;
        background: linear-gradient(to right,
            transparent 0%, rgba(255,255,255,.22) 18%,
            rgba(255,255,255,.22) 82%, transparent 100%)
            center / 100% 2px no-repeat;
        overflow: visible;
        margin: 1.6rem 0;
    }
    .block-container hr::after {
        content:""; position:absolute; top:50%; left:50%;
        width:20px; height:20px; border-radius:50%;
        transform: translate(-50%,-50%);
        background: linear-gradient(to bottom, var(--dex-red) 0 44%, #1a1a1a 44% 56%, #f5f5f5 56% 100%);
        border: 2.5px solid #1a1a1a;
        box-shadow: 0 0 0 6px var(--navy), 0 0 14px rgba(227,53,13,.5);
    }

    /* ---------- Sidebar ---------- */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #11172C 0%, #0C1122 100%);
        border-right: 1px solid var(--panel-edge);
    }
    [data-testid="stSidebar"]::before {
        content:""; display:block; height:8px;
        background: linear-gradient(90deg, var(--dex-red), var(--ball-yellow), var(--cerulean));
    }
    [data-testid="stSidebar"] h2 {
        font-family:'Baloo 2', sans-serif;
        color: var(--ball-yellow) !important;
        font-size: 1.05rem !important;
        letter-spacing:.5px;
    }

    /* ---------- Empty-State ---------- */
    .empty-state {
        text-align:center; padding: 3.2rem 1rem 3.6rem;
        border: 2px dashed var(--panel-edge); border-radius: 20px;
        background: rgba(255,255,255,.02);
        margin-top: 1rem;
    }
    .empty-ball {
        display:inline-block; width:74px; height:74px; border-radius:50%;
        background: linear-gradient(to bottom, var(--dex-red) 0 44%, #1a1a1a 44% 56%, #f5f5f5 56% 100%);
        border: 4px solid #1a1a1a; position:relative;
        animation: ballBounce 2.2s ease-in-out infinite;
        box-shadow: 0 14px 22px -10px rgba(0,0,0,.6);
    }
    .empty-ball::after {
        content:""; position:absolute; top:50%; left:50%;
        width:18px; height:18px; border-radius:50%;
        background:#f5f5f5; border:4px solid #1a1a1a;
        transform: translate(-50%,-50%);
    }
    @keyframes ballBounce {
        0%,100% { transform: translateY(0) rotate(0); }
        30%     { transform: translateY(-14px) rotate(-14deg); }
        55%     { transform: translateY(0) rotate(8deg); }
        70%     { transform: translateY(-5px) rotate(-4deg); }
    }
    .empty-title {
        font-family:'Baloo 2', sans-serif; font-weight:800;
        font-size:1.5rem; color: var(--text); margin-top: 1rem;
    }
    .empty-sub { color: var(--muted); margin-top:.3rem; }

    /* ---------- Reduced Motion ---------- */
    @media (prefers-reduced-motion: reduce) {
        .stApp::before, .poketool-title, .led, .dex-lens,
        .empty-ball, .dex-ball { animation: none !important; }
        .stButton > button, .stDownloadButton > button,
        [data-testid="stFileUploader"] section { transition: none; }
    }
    </style>
    """
    css = css.replace("__MAXW__", str(max_width_px)).replace("__PATTERN__", pokeball_pattern)

    header = """
    <div class="dex-bar">
        <div class="dex-lens"></div>
        <div class="dex-leds">
            <span class="led led-r"></span>
            <span class="led led-y"></span>
            <span class="led led-g"></span>
        </div>
        <div class="dex-title-wrap">
            <span class="poketool-title">7OwO7 Pok&eacute;tool</span>
            <span class="dex-tagline">SCAN &middot; IDENTIFIZIEREN &middot; GRADEN &middot; VERKAUFEN</span>
        </div>
        <span class="dex-ball"></span>
    </div>
    """
    st.markdown(video_html + css + header, unsafe_allow_html=True)


with st.sidebar:
    st.header("Ansicht")
    max_width = st.slider("Inhaltsbreite (px)", 900, 2400, 1500, 50)
    img_col_ratio = st.slider("Bildspalte breiter/schmaler", 0.5, 2.0, 1.0, 0.1)

    st.divider()
    st.header("PSA API")
    if "psa_token" not in st.session_state:
        st.session_state.psa_token = load_saved_token()
    st.session_state.psa_token = st.text_input(
        "PSA API Token", value=st.session_state.psa_token, type="password",
        help="Erzeugen unter psacard.com/publicapi (nach Login).",
    )
    remember = st.checkbox("Token merken (lokal in psa_token.txt speichern)")
    if remember and st.session_state.psa_token:
        save_token(st.session_state.psa_token)
    psa_token = st.session_state.psa_token

inject_style(max_width)

if not CV2_AVAILABLE:
    st.error("OpenCV fehlt - bitte `pip install -r requirements.txt` ausführen.")
    st.stop()


def auto_crop(pil_img):
    try:
        bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return Image.fromarray(cv2.cvtColor(crop_card_or_slab(bgr), cv2.COLOR_BGR2RGB))
    except Exception:
        return pil_img


def to_jpeg_bytes(pil_img):
    buf = io.BytesIO()
    pil_img.convert("RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ---------- Callbacks (laufen VOR dem Neuzeichnen -> darf Felder setzen) ----------

def rebuild_query(name):
    """Suchbegriff automatisch aus Name+Nummer+Set neu bauen -
    aber nur solange der Nutzer ihn nicht selbst editiert hat."""
    if st.session_state.get(f"query_manual_{name}"):
        return
    parts = [st.session_state.get(f"cardname_{name}", "").strip()]
    num = st.session_state.get(f"number_{name}", "").strip()
    if num:
        parts.append(num.split("/")[0])
    set_info = st.session_state.get(f"setinfo_{name}", "").split(",")[0].strip()
    if set_info:
        parts.append(set_info)
    st.session_state[f"query_{name}"] = " ".join(p for p in parts if p)


def mark_query_manual(name):
    st.session_state[f"query_manual_{name}"] = True


def apply_ocr(name):
    """Erkennen + Felder fuellen. Reihenfolge:
      1. Zertifikatsnummer + Firma erkannt -> Felder werden vorbelegt.
         WICHTIG: Der PSA-API-Pull passiert hier NICHT automatisch (nur 1
         Pull/Tag pro Token!) - dafuer muss der Nutzer weiter unten explizit
         auf "Zertifikat ueber PSA-API pruefen" klicken. CGC-Zertifikate
         werden weiterhin automatisch online abgeglichen (kein Kontingent-
         Limit / kein API-Token noetig, nur oeffentliches Scraping).
      2. Danach OCR-Werte nur fuer Felder, die noch leer sind.
      3. Zusaetzlich Kartendatenbank ueber die Nummer (fuer JP/DE-Karten).
    """
    data = st.session_state.cards[name]
    rec = recognize_card(data["final_cropped"])
    data["recognition"] = rec
    if not rec or rec.error:
        return

    filled = set()

    # --- Schritt 1: Zertifikat erkannt -> Nummer/Firma vorbelegen ---
    if rec.cert_number and rec.grading_company:
        st.session_state[f"cert_{name}"] = rec.cert_number
        st.session_state[f"gradco_{name}"] = rec.grading_company
        comp = rec.grading_company.upper()

        # PSA bewusst NICHT hier automatisch abfragen - der API-Pull ist auf
        # 1x/Tag pro Token limitiert. Der Nutzer bestaetigt das per Button
        # weiter unten (siehe "psaBtn_" Button in der Kartenanzeige).
        if "PSA" not in comp and supports_auto_lookup(rec.grading_company):
            cr = lookup_cert(rec.grading_company, rec.cert_number)
            data["cert_result"] = cr
            if cr and not cr.error:
                if cr.name:
                    st.session_state[f"cardname_{name}"] = cr.name
                    filled.add("name")
                if cr.grade:
                    st.session_state[f"grade_{name}"] = cr.grade
                    filled.add("grade")
                if cr.set_name:
                    st.session_state[f"setinfo_{name}"] = (
                        cr.set_name + (f", {cr.year}" if cr.year else ""))
                    filled.add("set")

    # --- Schritt 2: OCR-Werte fuer alles, was noch fehlt ---
    if "name" not in filled and rec.guessed_name:
        st.session_state[f"cardname_{name}"] = rec.guessed_name
    if rec.grading_company:
        st.session_state[f"gradco_{name}"] = rec.grading_company
    if "grade" not in filled and rec.grade:
        st.session_state[f"grade_{name}"] = rec.grade
    if "set" not in filled and rec.set_name:
        st.session_state[f"setinfo_{name}"] = (
            rec.set_name + (f", {rec.year}" if rec.year else ""))
    if "number" not in filled and rec.card_number:
        st.session_state[f"number_{name}"] = rec.card_number
    if rec.cert_number:
        st.session_state[f"cert_{name}"] = rec.cert_number

    rebuild_query(name)

    # --- Schritt 3: Kartendatenbank ueber die Nummer ---
    if rec.card_number:
        matches, err = lookup_by_number(rec.card_number, set_hint=rec.set_name or None)
        data["matches"] = matches
        data["lookup_error"] = err


def apply_lookup(name, chosen):
    st.session_state[f"cardname_{name}"] = chosen.name
    st.session_state[f"setinfo_{name}"] = (
        chosen.set_name
        + (f", {chosen.release_date[:4]}" if chosen.release_date else ""))
    st.session_state[f"number_{name}"] = chosen.full_number
    st.session_state[f"query_manual_{name}"] = False
    st.session_state[f"query_{name}"] = chosen.pricecharting_query


def apply_psa_result(name):
    data = st.session_state.cards[name]
    pr = data.get("psa_result")
    if not pr or pr.error:
        return
    if pr.name:
        st.session_state[f"cardname_{name}"] = pr.name
    if pr.grade:
        st.session_state[f"grade_{name}"] = pr.grade
    if pr.set_name:
        st.session_state[f"setinfo_{name}"] = (
            pr.set_name + (f", {pr.year}" if pr.year else ""))
    if pr.card_number:
        st.session_state[f"number_{name}"] = pr.card_number
    rebuild_query(name)


def apply_cert(name):
    data = st.session_state.cards[name]
    cr = data.get("cert_result")
    if not cr:
        return
    if cr.name:
        st.session_state[f"cardname_{name}"] = cr.name
    if cr.grade:
        st.session_state[f"grade_{name}"] = cr.grade
    if cr.set_name:
        st.session_state[f"setinfo_{name}"] = (
            cr.set_name + (f", {cr.year}" if cr.year else ""))
    rebuild_query(name)


# ---------- Upload ----------

uploaded_files = st.file_uploader(
    "Bilder hierher ziehen oder auswählen",
    type=["jpg", "jpeg", "png", "heic"],
    accept_multiple_files=True,
)

if "cards" not in st.session_state:
    st.session_state.cards = {}

current_names = {uf.name for uf in uploaded_files} if uploaded_files else set()
for stale in [n for n in st.session_state.cards if n not in current_names]:
    del st.session_state.cards[stale]
    for prefix in ("side_", "cardname_", "setinfo_", "gradco_", "grade_", "query_",
                   "query_manual_", "number_", "cert_", "text_", "text_fp_",
                   "cropper_", "rot_coarse_", "rot_fine_", "cand_", "link_",
                   "lookup_", "dlsel_"):
        st.session_state.pop(f"{prefix}{stale}", None)

if not uploaded_files:
    st.markdown(
        """
        <div class="empty-state">
            <span class="empty-ball"></span>
            <div class="empty-title">Wirf eine Karte rein!</div>
            <div class="empty-sub">Bilder oben ablegen &ndash; Foto vom Slab oder der rohen Karte.<br>
            Erkennung, Zertifikat, Preis und Verkaufstext kommen dann automatisch.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

for uf in uploaded_files:
    if uf.name not in st.session_state.cards:
        try:
            pil_img = Image.open(uf).convert("RGB")
        except Exception as exc:
            st.error(f"{uf.name}: Bild konnte nicht geöffnet werden ({exc}).")
            continue
        st.session_state.cards[uf.name] = {
            "original": pil_img, "final_cropped": pil_img,
            "recognition": None, "matches": None, "lookup_error": None,
            "candidates": None, "prices": None, "cert_result": None,
        }

st.divider()

front_names = [n for n in st.session_state.cards
               if st.session_state.get(f"side_{n}", "front") == "front"]
# Rueckseiten-Zuordnung: front -> back
back_of = {}
for n in st.session_state.cards:
    if st.session_state.get(f"side_{n}") == "back":
        linked = st.session_state.get(f"link_{n}")
        if linked:
            back_of[linked] = n

for name, data in st.session_state.cards.items():
    st.subheader(name)
    col1, col2 = st.columns([img_col_ratio, 1.4])

    with col1:
        coarse = st.radio("Drehen", ["0°", "90°", "180°", "270°"],
                          horizontal=True, key=f"rot_coarse_{name}")
        fine = st.slider("Feindrehung (°)", -15.0, 15.0, 0.0, 0.5, key=f"rot_fine_{name}")
        angle = {"0°": 0, "90°": 90, "180°": 180, "270°": 270}[coarse] + fine

        rotated = data["original"]
        if angle:
            rotated = rotated.rotate(-angle, expand=True, resample=Image.BICUBIC,
                                     fillcolor=(255, 255, 255))

        applied = data.get("applied_angle", 0)
        if angle != applied:
            # Vorschau: Regler laesst sich frei bewegen, ohne dass der
            # Zuschnitt-Rahmen bei jedem Tick neu aufgebaut wird.
            st.image(rotated, caption=f"Vorschau: {angle}° (noch nicht übernommen)",
                     use_container_width=True)
            if st.button("✅ Drehung übernehmen & zuschneiden", key=f"applyRot_{name}"):
                data["rotated"] = rotated
                data["auto_cropped"] = auto_crop(rotated)
                data["applied_angle"] = angle
                data["crop_gen"] = data.get("crop_gen", 0) + 1
                st.rerun()
        if "auto_cropped" not in data:
            data["rotated"] = rotated
            data["auto_cropped"] = auto_crop(rotated)
            data["applied_angle"] = angle
            data["crop_gen"] = 0

        if st.button("✂️ Auto-Zuschnitt neu berechnen", key=f"recrop_{name}"):
            data["auto_cropped"] = auto_crop(data.get("rotated", data["original"]))
            data["crop_gen"] = data.get("crop_gen", 0) + 1
            st.rerun()

        st.caption(f"Zuschnitt (Basis: {data.get('applied_angle', 0)}° gedreht) - "
                   "Rahmen ziehen zum Nachjustieren:")
        if CROPPER_AVAILABLE:
            data["final_cropped"] = st_cropper(
                data["auto_cropped"], realtime_update=True,
                box_color="#FFCB05", aspect_ratio=None,
                key=f"cropper_{name}_{data.get('crop_gen', 0)}")
        else:
            st.image(data["auto_cropped"], use_container_width=True)
            data["final_cropped"] = data["auto_cropped"]

    with col2:
        side = st.selectbox("Seite", ["front", "back"], key=f"side_{name}")

        if side == "front":
            st.button("🔎 Erkennen + Zertifikat & Datenbank abgleichen", key=f"ocrBtn_{name}",
                      on_click=apply_ocr, args=(name,))

            rec = data["recognition"]
            if rec:
                if rec.error:
                    st.warning(rec.error)
                    st.caption(f"Diagnose: {rec.debug_info}")
                else:
                    st.caption(f"Erkannt mit: {rec.engine_used}")
                    with st.expander("Erkannter Rohtext"):
                        st.text(rec.raw_text)
            if data.get("lookup_error"):
                st.warning(data["lookup_error"])

            card_name = st.text_input("Kartenname", key=f"cardname_{name}",
                                      on_change=rebuild_query, args=(name,))
            card_number = st.text_input("Kartennummer (z. B. 125/217)",
                                        key=f"number_{name}",
                                        on_change=rebuild_query, args=(name,))
            set_info = st.text_input("Set / Jahr", key=f"setinfo_{name}",
                                     on_change=rebuild_query, args=(name,))
            grading_company = st.text_input("Grading-Firma", key=f"gradco_{name}")
            grade = st.text_input("Note", key=f"grade_{name}")

            # ---- Karten-Datenbank ----
            lc1, lc2 = st.columns(2)
            with lc1:
                if st.button("🌍 Über Nummer identifizieren", key=f"lookupNumBtn_{name}"):
                    with st.spinner("Suche in Pokémon-TCG-Datenbank..."):
                        matches, err = lookup_by_number(
                            card_number, set_hint=(set_info.split(",")[0].strip() or None))
                        data["matches"], data["lookup_error"] = matches, err
            with lc2:
                if st.button("🔤 Über Namen identifizieren", key=f"lookupNameBtn_{name}"):
                    with st.spinner("Suche..."):
                        matches, err = lookup_by_name(card_name, card_number or None)
                        data["matches"], data["lookup_error"] = matches, err

            if data["matches"]:
                opts = {m.label: m for m in data["matches"]}
                chosen_label = st.selectbox("Passende Karte auswählen:",
                                            list(opts.keys()), key=f"lookup_{name}")
                chosen = opts[chosen_label]
                if chosen.image_url:
                    st.image(chosen.image_url, width=150,
                             caption="Referenzbild - stimmt es überein?")
                st.button("✅ Diese Karte übernehmen", key=f"applyLookup_{name}",
                          on_click=apply_lookup, args=(name, chosen))

            # ---- Zertifikat (nur bei erkannter Grading-Karte) ----
            if grading_company.strip():
                st.text_input("Zertifikatsnummer (vom Slab-Label)", key=f"cert_{name}")
                cnum = st.session_state.get(f"cert_{name}", "")
                comp_upper = grading_company.upper()

                if "PSA" in comp_upper:
                    if psa_token:
                        already = last_pull_today(psa_token)
                        if already:
                            st.info(
                                f"ℹ️ Heute bereits um {already.get('time', '?')} Uhr "
                                f"abgefragt (Zert. {already.get('cert', '?')}). "
                                "Tageslimit erreicht - morgen wieder möglich."
                            )
                        else:
                            confirm_key = f"psaConfirm_{name}"
                            if not st.session_state.get(confirm_key):
                                if st.button("🔐 Zertifikat über PSA-API prüfen", key=f"psaBtn_{name}"):
                                    st.session_state[confirm_key] = True
                                    st.rerun()
                            else:
                                st.warning(
                                    "⚠️ Nur **1 API-Pull pro Tag und Token** möglich. "
                                    "Wirklich jetzt abfragen?"
                                )
                                bc1, bc2 = st.columns(2)
                                with bc1:
                                    if st.button("✅ Ja, jetzt abfragen", key=f"psaConfirmYes_{name}"):
                                        with st.spinner("Frage PSA-API ab..."):
                                            data["psa_result"] = lookup_psa_cert(cnum, psa_token)
                                        st.session_state[confirm_key] = False
                                        st.rerun()
                                with bc2:
                                    if st.button("❌ Abbrechen", key=f"psaConfirmNo_{name}"):
                                        st.session_state[confirm_key] = False
                                        st.rerun()
                    else:
                        st.caption(
                            "Kein PSA-API-Token hinterlegt - in der Sidebar eintragen, "
                            "um Zertifikate automatisch abzugleichen.")
                    link = cert_url(grading_company, cnum)
                    if link:
                        st.caption(f"🔗 [Zertifikat auf psacard.com ansehen]({link})")
                elif supports_auto_lookup(grading_company):
                    if st.button("🔐 Zertifikat online prüfen", key=f"certBtn_{name}"):
                        with st.spinner("Prüfe Zertifikat..."):
                            data["cert_result"] = lookup_cert(grading_company, cnum)
                else:
                    link = cert_url(grading_company, cnum)
                    if link:
                        st.markdown(f"🔗 [Zertifikat bei {comp_upper} prüfen]({link})")

            psa_res = data.get("psa_result")
            if psa_res:
                if psa_res.error:
                    st.warning(psa_res.error)
                elif psa_res.raw:
                    with st.expander("PSA-API-Antwort"):
                        st.json(psa_res.raw)
                    st.button("✅ PSA-Daten übernehmen", key=f"applyPsa_{name}",
                              on_click=apply_psa_result, args=(name,))
            cr = data.get("cert_result")
            if cr:
                if cr.error:
                    st.warning(cr.error)
                if cr.url:
                    st.caption(f"Verifikationsseite: {cr.url}")
                if cr.fields:
                    with st.expander("Daten der Grading-Firma"):
                        st.table({"Feld": list(cr.fields.keys()),
                                  "Wert": list(cr.fields.values())})
                    st.button("✅ Zertifikatsdaten übernehmen", key=f"applyCert_{name}",
                              on_click=apply_cert, args=(name,))

            # ---- Preise ----
            st.text_input("Suchbegriff für pricecharting.com", key=f"query_{name}",
                          on_change=mark_query_manual, args=(name,))
            if st.button("🔍 Auf pricecharting.com suchen", key=f"searchBtn_{name}"):
                with st.spinner("Suche..."):
                    cands, err = search_candidates(
                        st.session_state.get(f"query_{name}", "") or card_name)
                    data["candidates"], data["prices"] = cands, None
                    if err:
                        st.warning(err)

            reference_price = ""
            if data["candidates"]:
                opts = {c.name + (f"  [{c.console}]" if c.console else ""): c
                        for c in data["candidates"]}
                lbl = st.selectbox("Richtigen Treffer auswählen:",
                                   list(opts.keys()), key=f"cand_{name}")
                if st.button("💲 Preise laden", key=f"priceBtn_{name}"):
                    with st.spinner("Lade Preise..."):
                        data["prices"] = get_prices_for_url(opts[lbl].url, opts[lbl].name)

            if data["prices"]:
                pr = data["prices"]
                if pr.error:
                    st.warning(pr.error)
                    if pr.product_url:
                        st.caption(f"Link: {pr.product_url}")
                if pr.prices:
                    rate = get_usd_eur_rate()
                    table = {"Zustand": list(pr.prices.keys()),
                             "Preis (USD)": list(pr.prices.values())}
                    if rate:
                        table["Preis (EUR)"] = [usd_string_to_eur(v, rate)
                                                for v in pr.prices.values()]
                        st.caption(f"Kurs: 1 USD = {rate:.4f} EUR")
                    st.table(table)
                    st.caption(f"Quelle: {pr.product_url}")
                    km = next((k for k in pr.prices if grade and grade in k), None)
                    usd_ref = pr.prices.get(km, next(iter(pr.prices.values()), ""))
                    reference_price = (usd_string_to_eur(usd_ref, rate)
                                       if rate and usd_ref else usd_ref) or usd_ref

            # ---- Dateiname + Verkaufstext ----
            suffix = f"{grading_company}{grade}" if grading_company or grade else ""
            base_name = card_name.strip() or name.rsplit(".", 1)[0]
            if card_number:
                base_name = f"{base_name} #{card_number.split('/')[0]}"
            filename = (f"{base_name} {suffix}".strip() if suffix else base_name) + "_front.jpg"

            fp = (base_name, set_info, grading_company, grade, reference_price)
            fpk, tk = f"text_fp_{name}", f"text_{name}"
            if st.session_state.get(fpk) != fp:
                st.session_state[tk] = generate_sales_text(
                    card_name=base_name, set_info=set_info,
                    grading_company=grading_company, grade=grade,
                    reference_price=reference_price)
                st.session_state[fpk] = fp
            st.text_area("Verkaufstext (editierbar)", key=tk, height=220)

            data["base_name"] = base_name
            data["export_filename"] = filename
            data["export_text"] = st.session_state[tk]

            # ---- Download-Auswahl ----
            st.caption(f"Dateiname: `{filename}`")
            dl_options = ["Front", "Verkaufstext"]
            if name in back_of:
                dl_options.insert(1, "Back")
            selection = st.multiselect("Was möchtest du herunterladen?",
                                       dl_options, default=dl_options,
                                       key=f"dlsel_{name}")
            cols = st.columns(max(len(selection), 1))
            for i, item in enumerate(selection):
                with cols[i]:
                    if item == "Front":
                        st.download_button(
                            "⬇️ Front", data=to_jpeg_bytes(data["final_cropped"]),
                            file_name=filename, mime="image/jpeg", key=f"dlF_{name}")
                    elif item == "Back" and name in back_of:
                        back_data = st.session_state.cards[back_of[name]]
                        st.download_button(
                            "⬇️ Back", data=to_jpeg_bytes(back_data["final_cropped"]),
                            file_name=filename.replace("_front.jpg", "_back.jpg"),
                            mime="image/jpeg", key=f"dlB_{name}")
                    elif item == "Verkaufstext":
                        st.download_button(
                            "⬇️ Text", data=data["export_text"],
                            file_name=filename.rsplit(".", 1)[0] + "_verkaufstext.txt",
                            mime="text/plain", key=f"dlT_{name}")

        else:  # back
            if front_names:
                linked = st.selectbox("Gehört zu (Vorderseite)", front_names,
                                      key=f"link_{name}")
                st.caption(f"Wird beim Download der Vorderseite **{linked}** "
                           "mit angeboten (Auswahl 'Back').")
            else:
                st.info("Noch keine Vorderseite vorhanden.")

    st.divider()
