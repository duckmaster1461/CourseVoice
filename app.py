import streamlit as st
import sqlite3
import pandas as pd
import json
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

st.set_page_config(
    page_title="CourseVoice",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_PATH = Path("coursevoice.db")

for k, v in {
    "dark_mode": True,
    "admin_logged_in": False,
    "admin_user": "",
    "admin_view": "home",
    "sort_by": "semester",
    "sort_order": "asc",
    "drill_link_id": None,
    "drill_subject": None,
    "gen_token": None,
    "submitted": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def get_conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def hpw(p): return hashlib.sha256(p.encode()).hexdigest()

def init_db():
    db = get_conn(); c = db.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS admins(
            id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT);
        CREATE TABLE IF NOT EXISTS subjects(
            id INTEGER PRIMARY KEY, name TEXT UNIQUE, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS questions(
            id INTEGER PRIMARY KEY, question_text TEXT NOT NULL,
            question_type TEXT NOT NULL, order_num INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS semester_links(
            id INTEGER PRIMARY KEY, label TEXT NOT NULL, token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS responses(
            id INTEGER PRIMARY KEY, link_id INTEGER NOT NULL, subject_name TEXT,
            answers_json TEXT NOT NULL, submitted_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    c.execute("INSERT OR IGNORE INTO admins(username, password_hash) VALUES(?,?)",
              ("admin", hpw("admin123")))
    if not c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]:
        c.executemany("INSERT INTO questions(question_text, question_type, order_num) VALUES(?,?,?)", [
            ("Which subject is this about?", "dropdown", 1),
            ("How has this course helped you?", "text", 2),
            ("How difficult was the course?", "rating", 3),
            ("Do you think the course should be offered again?", "yes_no", 4),
        ])
    for s in ["AP Physics 1","IB English HL","IB English SL","IM 1","IM 2","IM 3","Physics","Symphonic Band"]:
        c.execute("INSERT OR IGNORE INTO subjects(name) VALUES(?)", (s,))
    db.commit(); db.close()

init_db()

TOKEN      = st.query_params.get("token", None)
ADMIN_PARAM= st.query_params.get("admin", None)
DARK       = st.session_state.dark_mode
IS_ADMIN   = (ADMIN_PARAM is not None or st.session_state.admin_logged_in) and TOKEN is None
ACC        = "#FFD700"

# ── colour tokens ──────────────────────────────────────────────────────────────
if IS_ADMIN:
    BG   = "#4a6295"
    FG   = "#ffffff"
    INP  = "rgba(30,45,80,0.55)"
    BDR  = "rgba(255,215,0,0.85)"
    MUTED= "rgba(255,255,255,0.55)"
    CARD = "rgba(255,255,255,0.13)"
elif DARK:
    BG   = "#242424"
    FG   = "#e2e2e2"
    INP  = "#2e2e2e"
    BDR  = ACC
    MUTED= "#888888"
    CARD = "#2c2c2c"
else:
    BG   = "#e8e4d8"
    FG   = "#1a1a1a"
    INP  = "#ffffff"
    BDR  = "#1a1a1a"
    MUTED= "#777777"
    CARD = "#ffffff"

BTN_BG  = "#1a1a1a" if not IS_ADMIN else "transparent"
BTN_FG  = "#ffffff" if not IS_ADMIN else ACC

# ── global CSS ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&display=swap');

/* ensure predictable box model so borders/padding don't leak outside rounded corners */
*, *::before, *::after, html, body, .stApp, [class*="css"] {{ box-sizing: border-box !important; }}

*, html, body, [class*="css"] {{ font-family: 'Sora', sans-serif !important; }}

div[data-testid="stHorizontalBlock"] {{
    align-items: center !important;
}}

.stButton {{
    display: flex !important;
    justify-content: center !important;
    width: 100% !important;
}}
.stButton > button {{
    width: auto !important;
    min-width: unset !important;
}}
            
.stTextInput > div,
.stTextInput > div > div {{
    border-radius: 12px !important;
    overflow: hidden !important;
}}

.stSelectbox > div,
.stSelectbox > div > div {{
    border-radius: 12px !important;
    overflow: hidden !important;
}}
            
.stTextInput [data-testid="stWidgetLabel"],
.stSelectbox [data-testid="stWidgetLabel"],
.stTextArea [data-testid="stWidgetLabel"] {{
    display: none !important;
    min-height: 0 !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}}

/* page */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section[data-testid="stMainBlockContainer"] {{
    background-color: {BG} !important;
}}
.block-container {{
    background: transparent !important;
    padding: 1.4rem 2.2rem !important;
    max-width: 900px !important;
    margin: 0 auto !important;
}}
#MainMenu, footer, header, [data-testid="stToolbar"],
div[data-testid="stDecoration"] {{ visibility: hidden !important; display: none !important; }}

p, span, div, label, li {{ color: {FG} !important; }}
h1,h2,h3,h4,h5,h6 {{ color: {FG} !important; }}

/* ── text inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {{
    background: {INP} !important;
    color: {FG} !important;
    border: 2px solid {BDR} !important;
    border-radius: 12px !important;
    padding: 10px 22px !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.88rem !important;
    box-shadow: none !important;
    outline: none !important;
    background-clip: padding-box !important;
}}
.stTextInput > div > div > input::placeholder,
.stTextArea > div > div > textarea::placeholder {{
    color: {MUTED} !important;
    opacity: 1 !important;
}}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {{
    border-color: {ACC} !important;
    box-shadow: 0 0 0 1px {ACC}55 !important;
}}

/* ── selectbox ── */
.stSelectbox > div > div {{
    background: {INP} !important;
    color: {FG} !important;
    border: 2px solid {BDR} !important;
    border-radius: 12px !important;
    box-shadow: none !important;
    background-clip: padding-box !important;
}}
.stSelectbox > div > div > div {{ color: {FG} !important; }}
.stSelectbox > div > div svg {{ fill: {FG} !important; }}
div[data-baseweb="popover"] li {{ color: #1a1a1a !important; }}

/* ── ALL radio → pill/circle buttons ── */
div[data-testid="stRadio"] > label {{ display: none !important; }}
div[data-testid="stRadio"] [data-testid="stWidgetLabel"] {{
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
}}div[data-testid="stRadio"] > div {{
    flex-direction: row !important;
    flex-wrap: wrap !important;
    gap: 10px !important;
    align-items: center !important;
}}
div[data-testid="stRadio"] label {{
    border: 2px solid {ACC} !important;
    border-radius: 50px !important;
    min-width: 48px !important;
    height: 48px !important;
    padding: 0 18px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    cursor: pointer !important;
    background: transparent !important;
    color: {ACC} !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    margin: 0 !important;
    transition: background 0.15s, color 0.15s !important;
    white-space: nowrap !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
    position: relative !important;
    background-clip: padding-box !important;
    -webkit-background-clip: padding-box !important;
    z-index: 0 !important;
}}
div[data-testid="stRadio"] label:hover {{
    background: {ACC} !important;
    color: #111 !important;
}}
/* Use a more compatible checked rule (checked input inside label -> label gets active styles) */
div[data-testid="stRadio"] label input:checked + span,
div[data-testid="stRadio"] label input:checked ~ span {{
    background: {ACC} !important;
    color: #111 !important;
}}
/* Hide EVERYTHING inside the label except the last child (the text div) */
div[data-testid="stRadio"] label > *:not(:last-child) {{
    display: none !important;
    width: 0 !important;
    height: 0 !important;
    position: absolute !important;
    visibility: hidden !important;
    overflow: hidden !important;
    pointer-events: none !important;
}}
/* Make the text div fill properly */
div[data-testid="stRadio"] label > *:last-child {{
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    margin: 0 !important;
    padding: 0 !important;
}}
div[data-testid="stRadio"] label > *:last-child p {{
    margin: 0 !important;
    color: inherit !important;
    font-size: inherit !important;
    font-weight: inherit !important;
}}

/* VERTICAL radio (sort buttons stacked) */
div[data-testid="stRadio"].vertical-radio > div {{
    flex-direction: column !important;
    align-items: flex-start !important;
}}

/* ── main buttons ── */
.stButton > button {{
    background: transparent !important;
    overflow: visible !important;
    color: {ACC} !important;
    border: 2.5px solid {ACC} !important;
    border-radius: 30px !important;
    padding: 11px 32px !important;
    font-weight: 700 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    font-size: 0.82rem !important;
    font-family: 'Sora', sans-serif !important;
    transition: all 0.17s !important;
    white-space: nowrap !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
    background-clip: padding-box !important;
}}
.stButton > button:hover {{
    background: {ACC} !important;
    color: #111 !important;
    transform: translateY(-1px) !important;
}}

/* submit button (black/dark) */
.submit-btn .stButton > button {{
    background: {BTN_BG} !important;
    color: {BTN_FG} !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 14px 40px !important;
    letter-spacing: 2px !important;
    font-size: 0.88rem !important;
    width: 100% !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
}}

/* logout button — compact pill, never tall */
.logout-btn {{ display: flex !important; justify-content: flex-end !important; }}
.logout-btn .stButton > button {{
    border-radius: 30px !important;
    padding: 9px 22px !important;
    letter-spacing: 0.5px !important;
    font-size: 0.78rem !important;
    white-space: nowrap !important;
    min-width: 100px !important;
    width: auto !important;
    height: auto !important;
    text-transform: uppercase !important;
    font-weight: 700 !important;
    word-break: keep-all !important;
    overflow: hidden !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
    background-clip: padding-box !important;
}}

/* back button */
.back-btn .stButton > button {{
    border-radius: 30px !important;
    padding: 8px 22px !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.5px !important;
    text-transform: uppercase !important;
}}

/* semester/subject pills (outline, wider) */
.pill-btn .stButton > button {{
    border-radius: 12px !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    font-size: 0.82rem !important;
    padding: 14px 20px !important;
    width: 100% !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
}}
.pill-btn .stButton > button:hover {{
    background: {ACC} !important;
    color: #111 !important;
}}

/* admin large action buttons (outline style) */
.admin-action .stButton > button {{
    border-radius: 40px !important;
    text-transform: uppercase !important;
    letter-spacing: 2px !important;
    font-size: 0.88rem !important;
    padding: 18px 40px !important;
    width: 100% !important;
}}

/* remove (−) circle — prevent column from stretching it oval */
.rem-btn {{ display: flex !important; justify-content: center !important; }}
.rem-btn .stButton {{ max-width: 42px !important; width: 42px !important; }}
.rem-btn .stButton > button {{
    background: transparent !important;
    color: {ACC} !important;
    border: 2px solid {ACC} !important;
    border-radius: 50% !important;
    width: 38px !important;
    height: 38px !important;
    min-width: 38px !important;
    max-width: 38px !important;
    padding: 0 !important;
    font-size: 1.3rem !important;
    line-height: 38px !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    font-weight: 300 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
    background-clip: padding-box !important;
}}
.rem-btn .stButton > button:hover {{
    background: #e74c3c !important;
    border-color: #e74c3c !important;
    color: white !important;
    transform: none !important;
}}

/* add (+) circle button — prevent column from stretching it oval */
.add-btn {{ display: flex !important; justify-content: center !important; }}
.add-btn .stButton {{ max-width: 42px !important; width: 42px !important; }}
.add-btn .stButton > button {{
    background: transparent !important;
    color: {ACC} !important;
    border: 2px solid {ACC} !important;
    border-radius: 50% !important;
    width: 38px !important;
    height: 38px !important;
    min-width: 38px !important;
    max-width: 38px !important;
    padding: 0 !important;
    font-size: 1.3rem !important;
    line-height: 38px !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    font-weight: 300 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
    background-clip: padding-box !important;
}}
.add-btn .stButton > button:hover {{
    background: #27ae60 !important;
    border-color: #27ae60 !important;
    color: white !important;
    transform: none !important;
}}

/* save button */
.save-btn .stButton > button {{
    background: rgba(20,35,80,0.5) !important;
    color: white !important;
    border: 1.5px solid rgba(255,255,255,0.4) !important;
    border-radius: 10px !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    padding: 10px 28px !important;
    font-size: 0.88rem !important;
}}
.save-btn .stButton > button:hover {{
    background: rgba(10,20,60,0.8) !important;
    color: white !important;
    transform: none !important;
}}

/* arrow button */
.arrow-btn .stButton > button {{
    border-radius: 50% !important;
    min-width: 50px !important;
    width: 50px !important;
    height: 50px !important;
    padding: 0 !important;
    font-size: 1.3rem !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    font-weight: 400 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
    background-clip: padding-box !important;
}}

/* metric cards */
div[data-testid="stMetric"] {{
    background: {CARD} !important;
    border-radius: 12px !important;
    padding: 18px !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
}}
div[data-testid="stMetricValue"] {{ color: {FG} !important; font-size: 1.6rem !important; }}
div[data-testid="stMetricLabel"] {{ color: {MUTED} !important; font-size: 0.78rem !important; }}

/* expanders — fix icon text artifact */
.stExpander {{
    background: {CARD} !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}}
.stExpander summary {{
    color: {FG} !important;
}}
/* hide the SVG arrow icon text that leaks through */
.stExpander summary > div > div > p {{ color: {FG} !important; }}
details > summary > span {{ display: none !important; }}
details > summary > div {{ color: {FG} !important; }}

/* dataframe */
div[data-testid="stDataFrame"] {{
    border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
}}

/* toggle */
div[data-testid="stToggle"] label span {{ color: {FG} !important; }}

/* download button */
.stDownloadButton > button {{
    background: transparent !important;
    color: {ACC} !important;
    border: 2px solid {ACC} !important;
    border-radius: 30px !important;
    padding: 10px 28px !important;
    font-size: 0.82rem !important;
    font-family: 'Sora', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-sizing: border-box !important;
    background-clip: padding-box !important;
}}
.stDownloadButton > button:hover {{
    background: {ACC} !important;
    color: #111 !important;
}}

hr {{ border-color: rgba(255,255,255,0.2) !important; }}
code {{ background: rgba(0,0,0,0.3) !important; color: {ACC} !important;
        border-radius: 6px !important; padding: 2px 8px !important; }}
</style>
""", unsafe_allow_html=True)


# ═══ ADMIN HEADER (shared) ════════════════════════════════════════════════════
def render_admin_header():
    c1, _, c3 = st.columns([4, 3, 2])
    with c1:
        st.markdown(
            f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.6)">'
            f'Logged in as <strong style="color:white">{st.session_state.admin_user}</strong></div>',
            unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
        if st.button("Logout", key="logout_btn"):
            st.session_state.admin_logged_in = False
            st.session_state.admin_user = ""
            st.session_state.admin_view = "home"
            st.session_state.gen_token = None
            st.query_params.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<hr style="margin:8px 0 20px">', unsafe_allow_html=True)


# ═══ STUDENT SURVEY ═══════════════════════════════════════════════════════════
def page_student(token):
    # toggle top-right
    _, tcol = st.columns([8, 2])
    with tcol:
        nd = st.toggle("🌙 Dark mode", value=DARK, key="dm_t")
        if nd != DARK:
            st.session_state.dark_mode = nd
            st.rerun()

    db = get_conn()
    link = db.execute("SELECT * FROM semester_links WHERE token=?", (token,)).fetchone()
    if not link:
        db.close()
        st.error("❌ Invalid or expired survey link.")
        return

    subjects  = [r["name"] for r in db.execute(
        "SELECT name FROM subjects WHERE active=1 ORDER BY name").fetchall()]
    questions = db.execute(
        "SELECT * FROM questions WHERE active=1 ORDER BY order_num").fetchall()
    db.close()

    # success screen
    if st.session_state.submitted:
        _, cc, _ = st.columns([1, 3, 1])
        with cc:
            st.markdown(f"""
            <div style="text-align:center;padding:100px 0">
                <div style="font-size:3rem;margin-bottom:16px">🎉</div>
                <div style="font-size:1.8rem;font-weight:700;color:{FG}">Thank you!</div>
                <div style="font-size:0.9rem;color:{MUTED}">
                    Your feedback has been recorded anonymously.
                </div>
            </div>""", unsafe_allow_html=True)
        _, bc, _ = st.columns([1,4,1])
        with bc:
            if st.button("Submit another response", use_container_width=True):
                st.session_state.submitted = False
                st.rerun()
        return

    # header
    st.markdown(f"""
    <div style="text-align:center;padding:18px 0 28px">
        <div style="font-size:0.68rem;letter-spacing:3.5px;text-transform:uppercase;
                    color:{MUTED};margin-bottom:10px;font-weight:600">
            {link['label']}
        </div>
        <div style="font-size:2.2rem;font-weight:800;color:{FG};letter-spacing:-0.5px">
            Course Feedback
        </div>
        <div style="font-size:0.82rem;color:{MUTED};margin-top:10px">
            🔒 All responses are 100% anonymous
        </div>
    </div>""", unsafe_allow_html=True)

    # form — centered column
    _, col, _ = st.columns([1, 5, 1])
    with col:
        # card wrapper
        st.markdown(
            f'<div style="background:{CARD};border:1.5px solid rgba(255,215,0,0.25);'
            f'border-radius:18px;padding:36px 42px">',
            unsafe_allow_html=True)

        with st.form("sf", clear_on_submit=True):
            for i, q in enumerate(questions):
                if i > 0:
                    st.markdown(
                        f'<hr style="border:none;border-top:1px solid rgba(128,128,128,0.25);margin:20px 0">',
                        unsafe_allow_html=True)

                st.markdown(
                    f'<div style="font-size:0.9rem;color:{FG};margin-bottom:12px;font-weight:400">'
                    f'{q["question_text"]}</div>',
                    unsafe_allow_html=True)

                qt, qid = q["question_type"], q["id"]

                if qt == "dropdown":
                    st.selectbox(" ", ["— Select a subject —"] + subjects,
                                 label_visibility="collapsed", key=f"q{qid}")
                elif qt == "text":
                    st.text_input(" ", placeholder="Type your answer here…",
                                  label_visibility="collapsed", key=f"q{qid}")
                elif qt == "rating":
                    st.radio(" ", [1, 2, 3, 4, 5], index=2, horizontal=True,
                             label_visibility="collapsed", key=f"q{qid}")
                elif qt == "yes_no":
                    st.radio(" ", ["Yes", "No"], horizontal=True,
                             label_visibility="collapsed", key=f"q{qid}")

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<div class="submit-btn">', unsafe_allow_html=True)
            go = st.form_submit_button("SUBMIT", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            if go:
                ans, subj = {}, None
                for q in questions:
                    v = st.session_state.get(f"q{q['id']}")
                    ans[str(q["id"])] = str(v) if v is not None else ""
                    if q["question_type"] == "dropdown" and v and v != "— Select a subject —":
                        subj = v
                db2 = get_conn()
                db2.execute(
                    "INSERT INTO responses(link_id, subject_name, answers_json) VALUES(?,?,?)",
                    (link["id"], subj, json.dumps(ans)))
                db2.commit(); db2.close()
                st.session_state.submitted = True
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


# ═══ LANDING ══════════════════════════════════════════════════════════════════
def page_landing():
    _, tc = st.columns([8, 2])
    with tc:
        nd = st.toggle("🌙 Dark mode", value=DARK, key="dm_land")
        if nd != DARK:
            st.session_state.dark_mode = nd
            st.rerun()

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(f"""
        <div style="text-align:center;padding:80px 0 40px">
            <div style="font-size:3rem;font-weight:800;color:{FG};letter-spacing:-2px">CourseVoice</div>
            <div style="font-size:0.92rem;color:{MUTED};margin-top:10px;margin-bottom:44px">
                Anonymous course feedback platform
            </div>
        </div>""", unsafe_allow_html=True)

        st.markdown('<div style="display:flex;justify-content:center">', unsafe_allow_html=True)
        st.markdown('<div style="display:inline-block">', unsafe_allow_html=True)
        _, bc, _ = st.columns([2, 1, 2])
        with bc:
            if st.button("🔐 Admin Login"):
                st.query_params["admin"] = "1"
                st.rerun()
        st.markdown("</div></div>", unsafe_allow_html=True)

        st.markdown(f"""
        <div style="text-align:center;margin-top:32px;font-size:0.85rem;color:{MUTED}">
            Are you a student? Use the survey link your instructor shared with you.
        </div>""", unsafe_allow_html=True)


# ═══ ADMIN LOGIN ══════════════════════════════════════════════════════════════
def page_login():
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(f"""
        <div style="text-align:center;padding:70px 0 36px">
            <div style="font-size:2.6rem;font-weight:800;color:white;letter-spacing:-1.5px">CourseVoice</div>
            <div style="font-size:0.88rem;color:rgba(255,255,255,0.6);margin-top:8px">Admin Portal</div>
        </div>""", unsafe_allow_html=True)
        with st.form("login"):
            user = st.text_input("Username", placeholder="admin")
            pw   = st.text_input("Password", type="password", placeholder="••••••••")
            if st.form_submit_button("Sign In", use_container_width=True):
                db = get_conn()
                row = db.execute(
                    "SELECT * FROM admins WHERE username=? AND password_hash=?",
                    (user, hpw(pw))).fetchone()
                db.close()
                if row:
                    st.session_state.admin_logged_in = True
                    st.session_state.admin_user = user
                    st.query_params["admin"] = "1"
                    st.rerun()
                else:
                    st.error("Invalid credentials. Default: admin / admin123")


# ═══ ADMIN HOME ═══════════════════════════════════════════════════════════════
def page_admin_home():
    render_admin_header()

    st.markdown(f"""
    <div style="text-align:center;font-size:2.8rem;font-weight:800;color:white;
                letter-spacing:-1px;margin:0 0 36px">ADMIN VIEW</div>""",
                unsafe_allow_html=True)

    _, col, _ = st.columns([1, 3, 1])
    with col:
        st.markdown('<div class="admin-action">', unsafe_allow_html=True)
        if st.button("VIEW SURVEY RESULTS", use_container_width=True, key="go_results"):
            st.session_state.admin_view = "results"
            st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("ADD/EDIT SURVEY QUESTIONS", use_container_width=True, key="go_edit"):
            st.session_state.admin_view = "edit"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        # Generate link section
        st.markdown(f"""
        <div style="text-align:center;margin:36px 0 4px">
            <div style="font-size:1.15rem;font-weight:700;color:white">Generate new survey link</div>
            <div style="font-size:0.74rem;color:rgba(255,255,255,0.5);margin-top:6px">
                Note: editing questions does not affect already-generated links
            </div>
        </div>""", unsafe_allow_html=True)

        c1, c2 = st.columns([5, 1])
        with c1:
            sem_in = st.text_input(
                "_", placeholder="Enter the year and semester (e.g., 2025 Semester 1)",
                label_visibility="collapsed", key="sem_input")
        with c2:
            st.markdown('<div class="arrow-btn">', unsafe_allow_html=True)
            if st.button("→", key="gen_btn"):
                if sem_in and sem_in.strip():
                    tok = uuid.uuid4().hex[:8].upper()
                    db = get_conn()
                    db.execute("INSERT INTO semester_links(label,token) VALUES(?,?)",
                               (sem_in.strip(), tok))
                    db.commit(); db.close()
                    st.session_state.gen_token = tok
                    st.rerun()
                else:
                    st.warning("Enter a semester label first.")
            st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.gen_token:
            db = get_conn()
            lr = db.execute("SELECT label FROM semester_links WHERE token=?",
                            (st.session_state.gen_token,)).fetchone()
            db.close()
            tok = st.session_state.gen_token
            lbl = lr["label"] if lr else "?"
            st.markdown(f"""
            <div style="background:rgba(0,0,0,0.3);border-radius:10px;padding:14px 18px;
                        margin-top:12px;border:1px solid rgba(255,215,0,0.3)">
                <div style="font-size:0.76rem;color:{ACC};font-weight:600;margin-bottom:8px">
                    ✓ Link generated for <strong>{lbl}</strong>
                </div>
                <div style="font-size:0.8rem;color:rgba(255,255,255,0.7)">
                    Share this URL with students:
                </div>
            </div>""", unsafe_allow_html=True)
            st.code(f"?token={tok}")

    # recent links
    st.markdown('<hr style="margin:32px 0 20px">', unsafe_allow_html=True)
    db = get_conn()
    recent = db.execute(
        "SELECT sl.*, COUNT(r.id) as rc FROM semester_links sl "
        "LEFT JOIN responses r ON r.link_id=sl.id GROUP BY sl.id ORDER BY sl.created_at DESC LIMIT 6"
    ).fetchall()
    db.close()

    if recent:
        st.markdown(f'<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px">Recent survey links</div>',
                    unsafe_allow_html=True)
        for i in range(0, len(recent), 2):
            cols = st.columns(2)
            for j, row in enumerate(recent[i:i+2]):
                with cols[j]:
                    st.markdown(f"""
                    <div style="background:rgba(255,255,255,0.12);border-radius:12px;
                                padding:16px 20px;margin-bottom:10px;
                                border:1px solid rgba(255,255,255,0.18)">
                        <div style="font-weight:700;font-size:1rem;color:white">{row['label']}</div>
                        <div style="font-size:0.78rem;color:rgba(255,255,255,0.55);margin-top:6px">
                            {row['rc']} response(s) &nbsp;·&nbsp; token:
                            <code style="font-size:0.75rem">{row['token']}</code>
                        </div>
                    </div>""", unsafe_allow_html=True)


# ═══ SURVEY RESULTS INDEX ═════════════════════════════════════════════════════
def page_admin_results():
    render_admin_header()

    st.markdown(f"""
    <div style="text-align:center;font-size:2.6rem;font-weight:800;color:white;
                letter-spacing:-0.5px;margin:0 0 28px">SURVEY RESULTS</div>""",
                unsafe_allow_html=True)

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK", key="back_res"):
        st.session_state.admin_view = "home"
        st.rerun()
    st.markdown("</div><br>", unsafe_allow_html=True)

    # Sort controls — vertical stacks
    sc1, _, sc2 = st.columns([2, 1, 2])
    with sc1:
        st.markdown(f'<div style="font-size:0.82rem;font-weight:700;color:white;margin-bottom:8px">Sort by</div>',
                    unsafe_allow_html=True)
        sort_v = st.radio("_sb", ["Year and Semester", "Subjects"],
                          index=0 if st.session_state.sort_by == "semester" else 1,
                          key="sort_radio", label_visibility="hidden")
        st.session_state.sort_by = "semester" if "Semester" in sort_v else "subject"

    with sc2:
        st.markdown(f'<div style="font-size:0.82rem;font-weight:700;color:white;margin-bottom:8px">Order</div>',
                    unsafe_allow_html=True)
        ord_v = st.radio("_ob", ["Ascending", "Descending"],
                         index=0 if st.session_state.sort_order == "asc" else 1,
                         key="order_radio", label_visibility="hidden")
        st.session_state.sort_order = "asc" if ord_v == "Ascending" else "desc"

    st.markdown("<br>", unsafe_allow_html=True)

    db = get_conn()
    ORDER = "ASC" if st.session_state.sort_order == "asc" else "DESC"

    if st.session_state.sort_by == "semester":
        rows = db.execute(
            f"SELECT sl.*, COUNT(r.id) as cnt FROM semester_links sl "
            f"LEFT JOIN responses r ON r.link_id=sl.id GROUP BY sl.id ORDER BY sl.label {ORDER}"
        ).fetchall()
        db.close()
        if not rows:
            st.info("No survey links yet. Generate one from Admin home.")
            return
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for j, row in enumerate(rows[i:i+2]):
                with cols[j]:
                    st.markdown('<div class="pill-btn">', unsafe_allow_html=True)
                    lbl = f"{row['label'].upper()}  ({row['cnt']} RESPONSES)"
                    if st.button(lbl, key=f"s_{row['id']}", use_container_width=True):
                        st.session_state.drill_link_id = row["id"]
                        st.session_state.admin_view = "detail_semester"
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
    else:
        rows = db.execute(
            f"SELECT subject_name, COUNT(*) as cnt FROM responses "
            f"WHERE subject_name IS NOT NULL AND subject_name!='' "
            f"GROUP BY subject_name ORDER BY subject_name {ORDER}"
        ).fetchall()
        db.close()
        if not rows:
            st.info("No responses with subject data yet.")
            return
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for j, row in enumerate(rows[i:i+2]):
                with cols[j]:
                    st.markdown('<div class="pill-btn">', unsafe_allow_html=True)
                    lbl = f"{row['subject_name']}  ({row['cnt']})"
                    if st.button(lbl, key=f"subj_{row['subject_name']}", use_container_width=True):
                        st.session_state.drill_subject = row["subject_name"]
                        st.session_state.admin_view = "detail_subject"
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)


# ═══ DETAIL: SEMESTER ═════════════════════════════════════════════════════════
def page_admin_detail_semester():
    render_admin_header()

    link_id = st.session_state.drill_link_id
    db = get_conn()
    link      = db.execute("SELECT * FROM semester_links WHERE id=?", (link_id,)).fetchone()
    responses = db.execute(
        "SELECT * FROM responses WHERE link_id=? ORDER BY submitted_at DESC", (link_id,)).fetchall()
    questions = db.execute("SELECT * FROM questions ORDER BY order_num").fetchall()
    db.close()

    if not link:
        st.error("Semester not found."); return

    st.markdown(f"""
    <div style="text-align:center;font-size:2rem;font-weight:800;color:white;margin:0 0 24px">
        {link['label']}
    </div>""", unsafe_allow_html=True)

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK TO RESULTS", key="back_det_sem"):
        st.session_state.admin_view = "results"
        st.rerun()
    st.markdown("</div><br>", unsafe_allow_html=True)

    # metrics
    rating_qs = [q for q in questions if q["question_type"] == "rating"]
    all_r = []
    for r in responses:
        try:
            ans = json.loads(r["answers_json"])
            for rq in rating_qs:
                v = ans.get(str(rq["id"]))
                if v and str(v).isdigit(): all_r.append(int(v))
        except: pass

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Responses", len(responses))
    c2.metric("Avg Rating", f"{sum(all_r)/len(all_r):.1f}/5" if all_r else "N/A")
    unique_s = len(set(r["subject_name"] for r in responses if r["subject_name"]))
    c3.metric("Subjects", unique_s)

    if not responses:
        st.info("No responses yet."); return

    # chart
    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(f'<div style="font-weight:700;color:white;font-size:0.95rem;margin-bottom:12px">Responses by subject</div>',
                unsafe_allow_html=True)
    sc = {}
    for r in responses:
        s = r["subject_name"] or "Not specified"
        sc[s] = sc.get(s, 0) + 1
    if sc:
        df_sc = pd.DataFrame(sc.items(), columns=["Subject","Count"]).sort_values("Count", ascending=False)
        st.bar_chart(df_sc.set_index("Subject"))

    # individual responses
    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(f'<div style="font-weight:700;color:white;font-size:0.95rem;margin-bottom:12px">{len(responses)} Individual Responses</div>',
                unsafe_allow_html=True)

    for i, r in enumerate(responses):
        try: ans = json.loads(r["answers_json"])
        except: ans = {}
        subj = r["subject_name"] or "Unknown"
        date = r["submitted_at"][:10] if r["submitted_at"] else "—"
        with st.expander(f"Response #{i+1} — {subj} — {date}"):
            for q in questions:
                val = ans.get(str(q["id"]), "—")
                stars = "⭐" * int(val) if q["question_type"] == "rating" and str(val).isdigit() else ""
                st.markdown(f"""
                <div style="margin-bottom:14px">
                    <div style="font-size:0.74rem;font-weight:600;color:rgba(255,255,255,0.45);margin-bottom:3px">
                        {q['question_text']}
                    </div>
                    <div style="font-size:0.92rem;color:white">{val} {stars}</div>
                </div>""", unsafe_allow_html=True)

    # export
    st.markdown('<hr style="margin:20px 0">', unsafe_allow_html=True)
    rows_exp = []
    for r in responses:
        rd = {"Semester": link["label"], "Subject": r["subject_name"], "Date": r["submitted_at"]}
        try:
            ans = json.loads(r["answers_json"])
            for q in questions:
                rd[q["question_text"]] = ans.get(str(q["id"]), "")
        except: pass
        rows_exp.append(rd)
    if rows_exp:
        fn = f"responses_{link['label'].replace(' ','_')}.csv"
        st.download_button("⬇ Export CSV", pd.DataFrame(rows_exp).to_csv(index=False), fn, "text/csv")


# ═══ DETAIL: SUBJECT ══════════════════════════════════════════════════════════
def page_admin_detail_subject():
    render_admin_header()

    subj = st.session_state.drill_subject
    db = get_conn()
    responses = db.execute(
        """SELECT r.*, sl.label as sem_label FROM responses r
           JOIN semester_links sl ON r.link_id=sl.id
           WHERE r.subject_name=? ORDER BY r.submitted_at DESC""",
        (subj,)).fetchall()
    questions = db.execute("SELECT * FROM questions ORDER BY order_num").fetchall()
    db.close()

    st.markdown(f"""
    <div style="text-align:center;font-size:2rem;font-weight:800;color:white;margin:0 0 24px">
        {subj}
    </div>""", unsafe_allow_html=True)

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK TO RESULTS", key="back_det_subj"):
        st.session_state.admin_view = "results"
        st.rerun()
    st.markdown("</div><br>", unsafe_allow_html=True)

    all_r = []
    for r in responses:
        try:
            ans = json.loads(r["answers_json"])
            for q in questions:
                if q["question_type"] == "rating":
                    v = ans.get(str(q["id"]))
                    if v and str(v).isdigit(): all_r.append(int(v))
        except: pass

    c1, c2 = st.columns(2)
    c1.metric("Total Responses", len(responses))
    c2.metric("Avg Rating", f"{sum(all_r)/len(all_r):.1f}/5" if all_r else "N/A")

    if not responses:
        st.info("No responses for this subject."); return

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    for i, r in enumerate(responses):
        try: ans = json.loads(r["answers_json"])
        except: ans = {}
        with st.expander(f"Response #{i+1} — {r['sem_label']} — {r['submitted_at'][:10]}"):
            for q in questions:
                if q["question_type"] == "dropdown": continue
                val = ans.get(str(q["id"]), "—")
                stars = "⭐" * int(val) if q["question_type"] == "rating" and str(val).isdigit() else ""
                st.markdown(f"""
                <div style="margin-bottom:14px">
                    <div style="font-size:0.74rem;font-weight:600;color:rgba(255,255,255,0.45);margin-bottom:3px">
                        {q['question_text']}
                    </div>
                    <div style="font-size:0.92rem;color:white">{val} {stars}</div>
                </div>""", unsafe_allow_html=True)


# ═══ EDIT SURVEY ══════════════════════════════════════════════════════════════
def page_admin_edit():
    render_admin_header()

    st.markdown(f"""
    <div style="text-align:center;font-size:2.4rem;font-weight:800;color:white;
                letter-spacing:-0.5px;margin:0 0 24px">EDIT SURVEY</div>""",
                unsafe_allow_html=True)

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK", key="back_edit"):
        st.session_state.admin_view = "home"
        st.rerun()
    st.markdown("</div><br>", unsafe_allow_html=True)

    db = get_conn()
    questions = db.execute(
        "SELECT * FROM questions WHERE active=1 ORDER BY order_num").fetchall()
    db.close()

    TYPE_OPTS   = ["dropdown","text","rating","yes_no"]
    TYPE_LABELS = ["Dropdown ▼","Text","Rating (1-5)","Yes / No"]
    TYPE_MAP    = dict(zip(TYPE_OPTS, TYPE_LABELS))
    TYPE_REV    = dict(zip(TYPE_LABELS, TYPE_OPTS))

    # header row
    h0, h1, h2, h3 = st.columns([0.5, 4.5, 2.5, 1.2])
    for txt, col in [("No.", h0), ("Question", h1), ("Type", h2), ("Remove", h3)]:
        col.markdown(
            f'<div style="font-size:0.78rem;font-weight:700;color:rgba(255,255,255,0.55);'
            f'padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.2)">{txt}</div>',
            unsafe_allow_html=True)

    st.markdown("")

    for i, q in enumerate(questions):
        c0, c1, c2, c3 = st.columns([0.5, 4.5, 2.5, 1.2])
        with c0:
            st.markdown(
                f'<div style="padding:14px 0;font-size:0.9rem;color:rgba(255,255,255,0.7)">{i+1}</div>',
                unsafe_allow_html=True)
        with c1:
            st.text_input("_", value=q["question_text"],
                          label_visibility="collapsed", key=f"qt_{q['id']}")
        with c2:
            cur_lbl = TYPE_MAP.get(q["question_type"], "Text")
            idx = TYPE_LABELS.index(cur_lbl) if cur_lbl in TYPE_LABELS else 1
            st.selectbox("_", TYPE_LABELS, index=idx,
                         label_visibility="collapsed", key=f"qtp_{q['id']}")
        with c3:
            st.markdown('<div class="rem-btn">', unsafe_allow_html=True)
            if st.button("−", key=f"rm_{q['id']}"):
                db2 = get_conn()
                db2.execute("UPDATE questions SET active=0 WHERE id=?", (q["id"],))
                db2.commit(); db2.close()
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # save all
    st.markdown("<br>", unsafe_allow_html=True)
    _, sc, _ = st.columns([1,2,1])
    with sc:
        st.markdown('<div class="save-btn">', unsafe_allow_html=True)
        if st.button("💾 SAVE ALL CHANGES", use_container_width=True, key="save_all"):
            db2 = get_conn()
            for q in questions:
                nt  = st.session_state.get(f"qt_{q['id']}", q["question_text"])
                nl  = st.session_state.get(f"qtp_{q['id']}", TYPE_MAP.get(q["question_type"]))
                ntp = TYPE_REV.get(nl, q["question_type"])
                db2.execute("UPDATE questions SET question_text=?, question_type=? WHERE id=?",
                            (nt, ntp, q["id"]))
            db2.commit(); db2.close()
            st.success("Saved!")
        st.markdown("</div>", unsafe_allow_html=True)

    # add new question
    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:0.82rem;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:10px">Add new question</div>',
                unsafe_allow_html=True)

    na0, na1, na2, na3 = st.columns([0.5, 4.5, 2.5, 1.2])
    with na0:
        st.markdown(
            f'<div style="padding:14px 0;font-size:0.9rem;color:rgba(255,255,255,0.35)">{len(questions)+1}</div>',
            unsafe_allow_html=True)
    with na1:
        nq_text = st.text_input("_", placeholder="New question text…",
                                label_visibility="collapsed", key="nq_text")
    with na2:
        nq_type_lbl = st.selectbox("_", TYPE_LABELS,
                                   label_visibility="collapsed", key="nq_type")
    with na3:
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("＋", key="add_q"):
            if nq_text.strip():
                ntp = TYPE_REV.get(nq_type_lbl, "text")
                db2 = get_conn()
                mo = db2.execute("SELECT MAX(order_num) FROM questions").fetchone()[0] or 0
                db2.execute("INSERT INTO questions(question_text,question_type,order_num) VALUES(?,?,?)",
                            (nq_text.strip(), ntp, mo + 1))
                db2.commit(); db2.close()
                st.rerun()
            else:
                st.warning("Enter question text.")
        st.markdown("</div>", unsafe_allow_html=True)

    # subjects section
    st.markdown('<hr style="margin:28px 0">', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px">Subjects (for Dropdown question)</div>',
                unsafe_allow_html=True)

    db = get_conn()
    subjects = db.execute("SELECT * FROM subjects WHERE active=1 ORDER BY name").fetchall()
    db.close()

    for subj in subjects:
        s1, s2 = st.columns([7, 1.5])
        with s1:
            st.markdown(
                f'<div style="padding:10px 0;font-size:0.9rem;color:rgba(255,255,255,0.85)">• {subj["name"]}</div>',
                unsafe_allow_html=True)
        with s2:
            st.markdown('<div class="rem-btn">', unsafe_allow_html=True)
            if st.button("−", key=f"rs_{subj['id']}"):
                db2 = get_conn()
                db2.execute("UPDATE subjects SET active=0 WHERE id=?", (subj["id"],))
                db2.commit(); db2.close()
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    a1, a2 = st.columns([7, 1.5])
    with a1:
        ns = st.text_input("_", placeholder="Add new subject…",
                           label_visibility="collapsed", key="new_subj")
    with a2:
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("＋", key="add_s"):
            if ns.strip():
                db2 = get_conn()
                db2.execute("INSERT OR IGNORE INTO subjects(name) VALUES(?)", (ns.strip(),))
                db2.execute("UPDATE subjects SET active=1 WHERE name=?", (ns.strip(),))
                db2.commit(); db2.close()
                st.rerun()
            else:
                st.warning("Enter a subject name.")
        st.markdown("</div>", unsafe_allow_html=True)


# ═══ ADMIN DISPATCHER ═════════════════════════════════════════════════════════
def page_admin():
    av = st.session_state.admin_view
    if av == "home":              page_admin_home()
    elif av == "results":         page_admin_results()
    elif av == "detail_semester": page_admin_detail_semester()
    elif av == "detail_subject":  page_admin_detail_subject()
    elif av == "edit":            page_admin_edit()


# ═══ ROUTER ═══════════════════════════════════════════════════════════════════
if TOKEN:
    page_student(TOKEN)
elif ADMIN_PARAM is not None or st.session_state.admin_logged_in:
    if st.session_state.admin_logged_in:
        page_admin()
    else:
        page_login()
else:
    page_landing()
