import streamlit as st
import pandas as pd
import json
import hashlib
import uuid
from datetime import datetime
import time
import pymongo
from google import genai

# ═══ GEMINI ═══════════════════════════════════════════════════════════════════
GEMINI_MODEL = "gemini-2.0-flash"
_gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

def moderate_answer(question_text, answer_text):
    """Returns (is_acceptable, reason, tip) using Gemini."""
    prompt = f"""You are moderating a student course feedback survey.

Question: "{question_text}"
Student's answer: "{answer_text}"

Determine if this answer is genuine, constructive, and relevant (not gibberish or spam).
Also check it's at least somewhat detailed.

Respond ONLY with a JSON object like:
{{"acceptable": true}}
or
{{"acceptable": false, "reason": "brief explanation for the student", "tip": "specific suggestion to improve their answer"}}"""
    try:
        response = _gemini_client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
        if parsed.get("acceptable", True):
            return True, None, None
        else:
            return False, parsed.get("reason", "Please provide a more constructive answer."), parsed.get("tip", "")
    except Exception:
        return True, None, None

def check_llm_status():
    """Returns (is_online, response_time_ms, message)."""
    try:
        start = time.time()
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL, contents="Reply with only the word: OK"
        )
        elapsed = int((time.time() - start) * 1000)
        return True, elapsed, response.text.strip()
    except Exception as e:
        return False, None, str(e)


# ═══ MONGODB ══════════════════════════════════════════════════════════════════
@st.cache_resource
def init_connection():
    return pymongo.MongoClient(
        st.secrets["mongo"]["uri"],
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
        tls=True,
        tlsAllowInvalidCertificates=False,
    )

def get_db():
    return init_connection()["coursevoice"]

def next_id(collection_name):
    """Atomic auto-increment using a counters collection."""
    db = get_db()
    result = db.counters.find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=pymongo.ReturnDocument.AFTER
    )
    return result["seq"]

def ensure_defaults():
    """Seed the database with default data on first run."""
    db = get_db()

    def hpw(p): return hashlib.sha256(p.encode()).hexdigest()

    if db.admins.count_documents({}) == 0:
        db.admins.insert_one({"id": 1, "username": "admin", "password_hash": hpw("admin123")})
        db.counters.update_one({"_id": "admins"}, {"$set": {"seq": 1}}, upsert=True)

    if db.subjects.count_documents({}) == 0:
        default_subjects = ["AP Physics 1","IB English HL","IB English SL",
                            "IM 1","IM 2","IM 3","Physics","Symphonic Band"]
        db.subjects.insert_many([
            {"id": i+1, "name": s, "active": 1}
            for i, s in enumerate(default_subjects)
        ])
        db.counters.update_one({"_id": "subjects"}, {"$set": {"seq": len(default_subjects)}}, upsert=True)

    if db.questions.count_documents({}) == 0:
        db.questions.insert_many([
            {"id": 1, "question_text": "Which subject is this about?",                    "question_type": "dropdown", "order_num": 1, "active": 1, "ai_moderated": 0},
            {"id": 2, "question_text": "How has this course helped you?",                  "question_type": "text",     "order_num": 2, "active": 1, "ai_moderated": 1},
            {"id": 3, "question_text": "How difficult was the course?",                    "question_type": "rating",   "order_num": 3, "active": 1, "ai_moderated": 0},
            {"id": 4, "question_text": "Do you think the course should be offered again?", "question_type": "yes_no",   "order_num": 4, "active": 1, "ai_moderated": 0},
        ])
        db.counters.update_one({"_id": "questions"}, {"$set": {"seq": 4}}, upsert=True)


PROJ = {"_id": 0}  # exclude MongoDB _id from all queries


# ═══ APP CONFIG ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="CourseVoice",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
    "form_errors": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ensure_defaults runs once per session via session_state guard (see router)

def hpw(p): return hashlib.sha256(p.encode()).hexdigest()

TOKEN       = st.query_params.get("token", None)
ADMIN_PARAM = st.query_params.get("admin", None)
DARK        = st.session_state.dark_mode
IS_ADMIN    = (ADMIN_PARAM is not None or st.session_state.admin_logged_in) and TOKEN is None
ACC         = "#FFD700"

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

if IS_ADMIN:
    BTN_BG   = "transparent"
    BTN_FG   = ACC
    RADIO_BG = "#1a1a1a"
elif DARK:
    BTN_BG   = "#1a1a1a"
    BTN_FG   = "#ffffff"
    RADIO_BG = "#1a1a1a"
else:
    BTN_BG   = INP
    BTN_FG   = "#1a1a1a"
    RADIO_BG = "#555555"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&display=swap');

*, *::before, *::after, html, body, .stApp, [class*="css"] {{ box-sizing: border-box; }}
*, html, body, [class*="css"] {{ font-family: 'Sora', sans-serif; }}

div[data-testid="stHorizontalBlock"] {{ align-items: center; }}

.stButton {{ display: flex; justify-content: center; width: 100%; }}
.stButton > button {{ width: auto; min-width: unset; }}

.stTextInput > div,
.stTextInput > div > div {{ border-radius: 12px; overflow: hidden; }}
.stSelectbox > div,
.stSelectbox > div > div {{ border-radius: 12px; overflow: hidden; }}

.stTextInput [data-testid="stWidgetLabel"],
.stSelectbox [data-testid="stWidgetLabel"],
.stTextArea [data-testid="stWidgetLabel"] {{
    display: none; min-height: 0; height: 0; margin: 0; padding: 0;
}}

html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section[data-testid="stMainBlockContainer"] {{ background-color: {BG}; }}
.block-container {{
    background: transparent;
    padding: 1.4rem 2.2rem;
    max-width: 900px;
    margin: 0 auto;
}}
#MainMenu, footer, header, [data-testid="stToolbar"],
div[data-testid="stDecoration"] {{ visibility: hidden; display: none; }}

p, span, div, label, li {{ color: {FG}; }}
h1,h2,h3,h4,h5,h6 {{ color: {FG}; }}

.stTextInput > div > div > input,
.stTextArea > div > div > textarea {{
    background: {INP};
    color: {FG};
    border: 2px solid {BDR};
    border-radius: 12px;
    padding: 10px 22px;
    font-family: 'Sora', sans-serif;
    font-size: 0.88rem;
    box-shadow: none;
    outline: none;
    background-clip: padding-box;
}}
.stTextInput > div > div > input::placeholder,
.stTextArea > div > div > textarea::placeholder {{ color: {MUTED}; opacity: 1; }}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {{
    border-color: {ACC};
    box-shadow: 0 0 0 1px {ACC}55;
}}

.stSelectbox > div > div {{
    background: {INP};
    color: {FG};
    border: 2px solid {BDR};
    border-radius: 12px;
    box-shadow: none;
    background-clip: padding-box;
}}
.stSelectbox > div > div > div {{ color: {FG}; }}
.stSelectbox > div > div svg {{ fill: {FG}; }}
div[data-baseweb="popover"] li {{ color: #1a1a1a; }}

div[data-testid="stRadio"] > label {{ display: none; }}
div[data-testid="stRadio"] [data-testid="stWidgetLabel"] {{
    display: none; height: 0; margin: 0; padding: 0; min-height: 0;
}}
div[data-testid="stRadio"] > div {{
    flex-direction: row; flex-wrap: wrap; gap: 10px; align-items: center;
}}
div[data-testid="stRadio"] label {{
    border: 2px solid {BDR};
    border-radius: 50px;
    min-width: 48px;
    height: 48px;
    padding: 0 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    background: {RADIO_BG};
    color: #ffffff;
    font-weight: 600;
    font-size: 0.9rem;
    margin: 0;
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
    box-sizing: border-box;
    overflow: hidden;
    position: relative;
    background-clip: padding-box;
    -webkit-background-clip: padding-box;
    z-index: 0;
}}
div[data-testid="stRadio"] label:hover {{ background: {BDR}; color: #1a1a1a; }}
div[data-testid="stRadio"] label:has(input:checked) {{
    background: {ACC} !important;
    color: #111 !important;
    border-color: {ACC} !important;
}}
div[data-testid="stRadio"] label > *:not(:last-child) {{
    display: none; width: 0; height: 0; position: absolute;
    visibility: hidden; overflow: hidden; pointer-events: none;
}}
div[data-testid="stRadio"] label > *:last-child {{
    display: flex; align-items: center; justify-content: center; margin: 0; padding: 0;
}}
div[data-testid="stRadio"] label > *:last-child p {{
    margin: 0; color: inherit; font-size: inherit; font-weight: inherit;
}}

.stButton > button {{
    background: transparent;
    overflow: visible;
    color: {ACC};
    border: 2.5px solid {ACC};
    border-radius: 30px;
    padding: 11px 32px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    font-size: 0.82rem;
    font-family: 'Sora', sans-serif;
    transition: all 0.17s;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    background-clip: padding-box;
}}
.stButton > button:hover {{ background: {ACC}; color: #111; transform: translateY(-1px); }}

[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button {{
    background: {BTN_BG} !important;
    color: {BTN_FG} !important;
    border: 2px solid {BDR} !important;
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
[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button p,
[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button span,
[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button div {{
    color: {BTN_FG} !important;
}}

.logout-btn {{ display: flex; justify-content: flex-end; }}
.logout-btn .stButton > button {{
    border-radius: 30px;
    padding: 9px 22px;
    letter-spacing: 0.5px;
    font-size: 0.78rem;
    white-space: nowrap;
    min-width: 100px;
    width: auto;
    height: auto;
    text-transform: uppercase;
    font-weight: 700;
    word-break: keep-all;
    overflow: hidden;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    background-clip: padding-box;
}}

.back-btn .stButton > button {{
    border-radius: 30px;
    padding: 8px 22px;
    font-size: 0.82rem;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}

.pill-btn .stButton > button {{
    border-radius: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 0.82rem;
    padding: 14px 20px;
    width: 100%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
}}
.pill-btn .stButton > button:hover {{ background: {ACC}; color: #111; }}

.admin-action .stButton > button {{
    border-radius: 40px;
    text-transform: uppercase;
    letter-spacing: 2px;
    font-size: 0.88rem;
    padding: 18px 40px;
    width: 100%;
}}

.rem-btn {{ display: flex; justify-content: center; }}
.rem-btn .stButton {{ max-width: 42px; width: 42px; }}
.rem-btn .stButton > button {{
    background: transparent;
    color: {ACC};
    border: 2px solid {ACC};
    border-radius: 50%;
    width: 38px; height: 38px; min-width: 38px; max-width: 38px;
    padding: 0;
    font-size: 1.3rem;
    line-height: 38px;
    letter-spacing: 0;
    text-transform: none;
    font-weight: 300;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    background-clip: padding-box;
}}
.rem-btn .stButton > button:hover {{
    background: #e74c3c; border-color: #e74c3c; color: white; transform: none;
}}

.add-btn {{ display: flex; justify-content: center; }}
.add-btn .stButton {{ max-width: 42px; width: 42px; }}
.add-btn .stButton > button {{
    background: transparent;
    color: {ACC};
    border: 2px solid {ACC};
    border-radius: 50%;
    width: 38px; height: 38px; min-width: 38px; max-width: 38px;
    padding: 0;
    font-size: 1.3rem;
    line-height: 38px;
    letter-spacing: 0;
    text-transform: none;
    font-weight: 300;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    background-clip: padding-box;
}}
.add-btn .stButton > button:hover {{
    background: #27ae60; border-color: #27ae60; color: white; transform: none;
}}

.save-btn .stButton > button {{
    background: rgba(20,35,80,0.5);
    color: white;
    border: 1.5px solid rgba(255,255,255,0.4);
    border-radius: 10px;
    text-transform: none;
    letter-spacing: 0;
    padding: 10px 28px;
    font-size: 0.88rem;
}}
.save-btn .stButton > button:hover {{ background: rgba(10,20,60,0.8); color: white; transform: none; }}

.arrow-btn .stButton > button {{
    border-radius: 50%;
    min-width: 50px; width: 50px; height: 50px;
    padding: 0;
    font-size: 1.3rem;
    letter-spacing: 0;
    text-transform: none;
    font-weight: 400;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    background-clip: padding-box;
}}

div[data-testid="stMetric"] {{
    background: {CARD};
    border-radius: 12px;
    padding: 18px;
    border: 1px solid rgba(255,255,255,0.2);
}}
div[data-testid="stMetricValue"] {{ color: {FG}; font-size: 1.6rem; }}
div[data-testid="stMetricLabel"] {{ color: {MUTED}; font-size: 0.78rem; }}

.stExpander {{
    background: {CARD};
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    overflow: hidden;
}}
.stExpander summary {{ color: {FG}; }}
.stExpander summary > div > div > p {{ color: {FG}; }}
details > summary > span {{ display: none; }}
details > summary > div {{ color: {FG}; }}

div[data-testid="stDataFrame"] {{
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.15);
}}

div[data-testid="stToggle"] label span {{ color: {FG}; }}

.stDownloadButton > button {{
    background: transparent;
    color: {ACC};
    border: 2px solid {ACC};
    border-radius: 30px;
    padding: 10px 28px;
    font-size: 0.82rem;
    font-family: 'Sora', sans-serif;
    font-weight: 600;
    letter-spacing: 1px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    background-clip: padding-box;
}}
.stDownloadButton > button:hover {{ background: {ACC}; color: #111; }}

hr {{ border-color: rgba(255,255,255,0.2); }}
code {{ background: rgba(0,0,0,0.3); color: {ACC}; border-radius: 6px; padding: 2px 8px; }}
</style>
""", unsafe_allow_html=True)




# ═══ ADMIN HEADER ═════════════════════════════════════════════════════════════
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
    _, tcol = st.columns([8, 2])
    with tcol:
        nd = st.toggle("🌙 Dark mode", value=DARK, key="dm_t")
        if nd != DARK:
            st.session_state.dark_mode = nd
            st.rerun()

    db   = get_db()
    link = db.semester_links.find_one({"token": token}, PROJ)
    if not link:
        st.error("❌ Invalid or expired survey link.")
        return

    subjects  = [s["name"] for s in sorted(db.subjects.find({"active": 1}, PROJ), key=lambda x: x["name"])]
    questions = sorted(db.questions.find({"active": 1}, PROJ), key=lambda x: x["order_num"])

    if st.session_state.submitted:
        _, cc, _ = st.columns([1, 3, 1])
        with cc:
            st.markdown(f"""
            <div style="text-align:center;padding:100px 0">
                <div style="font-size:3rem;margin-bottom:16px">🎉</div>
                <div style="font-size:1.8rem;font-weight:700;color:{FG}">Thank you!</div>
                <div style="font-size:0.9rem;color:{MUTED}">Your feedback has been recorded anonymously.</div>
            </div>""", unsafe_allow_html=True)
        _, bc, _ = st.columns([1, 4, 1])
        with bc:
            if st.button("Submit another response", use_container_width=True):
                st.session_state.submitted = False
                st.rerun()
        return

    st.markdown(f"""
    <div style="text-align:center;padding:18px 0 28px">
        <div style="font-size:0.68rem;letter-spacing:3.5px;text-transform:uppercase;
                    color:{MUTED};margin-bottom:10px;font-weight:600">{link['label']}</div>
        <div style="font-size:2.2rem;font-weight:800;color:{FG};letter-spacing:-0.5px">Course Feedback</div>
        <div style="font-size:0.82rem;color:{MUTED};margin-top:10px">🔒 All responses are 100% anonymous</div>
    </div>""", unsafe_allow_html=True)

    if st.session_state.form_errors:
        for e in st.session_state.form_errors:
            if isinstance(e, dict):
                st.markdown(
                    f'<div style="background:#5c1a1a;border:1px solid #e74c3c;border-radius:8px;' 
                    f'padding:12px 16px;margin:8px 0;color:#ff6b6b;font-size:0.88rem">' 
                    f'⚠️ {e["msg"]}</div>', unsafe_allow_html=True)
                if e.get("tip"):
                    st.markdown(
                        f'<div style="background:#1a2f4a;border:1px solid #3a7bd5;border-radius:8px;' 
                        f'padding:12px 16px;margin:4px 0 8px;color:#7eb8f7;font-size:0.88rem">' 
                        f'💡 Tip: {e["tip"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="background:#5c1a1a;border:1px solid #e74c3c;border-radius:8px;' 
                    f'padding:12px 16px;margin:8px 0;color:#ff6b6b;font-size:0.88rem">' 
                    f'⚠️ {e}</div>', unsafe_allow_html=True)
        st.session_state.form_errors = []

    with st.form("sf", clear_on_submit=False):
        for i, q in enumerate(questions):
            if i > 0:
                st.markdown('<hr style="border:none;border-top:1px solid rgba(128,128,128,0.25);margin:20px 0">', unsafe_allow_html=True)
            st.markdown(
                f'<div style="font-size:0.9rem;color:{FG};margin-bottom:12px;font-weight:400">' 
                f'{q["question_text"]}</div>', unsafe_allow_html=True)

            qt, qid = q["question_type"], q["id"]
            if qt == "dropdown":
                st.selectbox(" ", ["— Select a subject —"] + subjects,
                             label_visibility="collapsed", key=f"q{qid}")
            elif qt == "text":
                val = st.text_input(" ", placeholder="Type your answer here…",
                                    label_visibility="collapsed", key=f"q{qid}")
                char_count = len(val) if val else 0
                counter_color = "#e74c3c" if char_count < 50 else "#27ae60"
                st.markdown(
                    f'<div style="text-align:right;font-size:0.75rem;color:{counter_color};' 
                    f'margin-top:4px">{char_count} chars (aim for 50+)</div>',
                    unsafe_allow_html=True)
            elif qt == "rating":
                st.radio(" ", [1, 2, 3, 4, 5], index=None, horizontal=True,
                         label_visibility="collapsed", key=f"q{qid}")
            elif qt == "yes_no":
                st.radio(" ", ["Yes", "No"], index=None, horizontal=True,
                         label_visibility="collapsed", key=f"q{qid}")

        st.markdown("<br>", unsafe_allow_html=True)
        go = st.form_submit_button("SUBMIT", use_container_width=True)

        if go:
            ans, subj = {}, None
            errors = []

            for q in questions:
                v = st.session_state.get(f"q{q['id']}")
                ans[str(q["id"])] = str(v) if v is not None else ""

                if q["question_type"] == "dropdown" and (not v or v == "— Select a subject —"):
                    errors.append("Please select a subject.")
                elif q["question_type"] == "text":
                    if not (v and str(v).strip()):
                        errors.append(f'"{q["question_text"]}" cannot be empty.')
                    elif q.get("ai_moderated", 0):
                        with st.spinner("Checking your answer…"):
                            acceptable, reason, tip = moderate_answer(q["question_text"], str(v).strip())
                        if not acceptable:
                            errors.append({"msg": f"Please revise your answer: {reason}", "tip": tip})
                elif q["question_type"] in ("rating", "yes_no") and v is None:
                    errors.append(f'Please answer: "{q["question_text"]}"'  )

                if q["question_type"] == "dropdown" and v and v != "— Select a subject —":
                    subj = v

            if errors:
                st.session_state.form_errors = errors
                st.rerun()
            else:
                rid = next_id("responses")
                get_db().responses.insert_one({
                    "id": rid, "link_id": link["id"], "subject_name": subj,
                    "answers_json": json.dumps(ans),
                    "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                st.session_state.submitted = True
                st.rerun()


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

        _, bc, _ = st.columns([2, 1, 2])
        with bc:
            if st.button("🔐 Admin Login"):
                st.query_params["admin"] = "1"
                st.rerun()

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
                db  = get_db()
                row = db.admins.find_one({"username": user, "password_hash": hpw(pw)}, PROJ)
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

        # ── LLM Status Check ──────────────────────────────────────────────────
        st.markdown('<hr style="margin:28px 0 20px">', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:12px;text-align:center">' 
            '🤖 AI Moderation Status</div>',
            unsafe_allow_html=True)

        llm_col1, llm_col2, llm_col3 = st.columns([1, 2, 1])
        with llm_col2:
            if st.button("Check AI Connection", use_container_width=True, key="llm_check"):
                with st.spinner("Pinging Gemini…"):
                    online, ms, msg = check_llm_status()
                st.session_state["llm_status"] = {"online": online, "ms": ms, "msg": msg}

        status = st.session_state.get("llm_status")
        if status is not None:
            if status["online"]:
                st.markdown(
                    f'<div style="background:rgba(39,174,96,0.18);border:1px solid #27ae60;' 
                    f'border-radius:10px;padding:14px 18px;margin-top:10px;text-align:center">' 
                    f'<div style="font-size:1.1rem;color:#2ecc71;font-weight:700">✅ Online</div>' 
                    f'<div style="font-size:0.78rem;color:rgba(255,255,255,0.6);margin-top:4px">' 
                    f'Responded in <strong style="color:white">{status["ms"]} ms</strong>' 
                    f' &nbsp;·&nbsp; Reply: <code>{status["msg"]}</code></div>' 
                    f'</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="background:rgba(92,26,26,0.6);border:1px solid #e74c3c;' 
                    f'border-radius:10px;padding:14px 18px;margin-top:10px;text-align:center">' 
                    f'<div style="font-size:1.1rem;color:#ff6b6b;font-weight:700">❌ Offline</div>' 
                    f'<div style="font-size:0.78rem;color:rgba(255,100,100,0.8);margin-top:4px">' 
                    f'{status["msg"]}</div>' 
                    f'</div>', unsafe_allow_html=True)

        st.markdown('<hr style="margin:20px 0">', unsafe_allow_html=True)

        st.markdown(f"""
        <div style="text-align:center;margin:0 0 4px">
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
                    lid = next_id("semester_links")
                    get_db().semester_links.insert_one({
                        "id": lid, "label": sem_in.strip(), "token": tok,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    st.session_state.gen_token = tok
                    st.rerun()
                else:
                    st.warning("Enter a semester label first.")
            st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.gen_token:
            db  = get_db()
            lr  = db.semester_links.find_one({"token": st.session_state.gen_token}, PROJ)
            tok = st.session_state.gen_token
            lbl = lr["label"] if lr else "?"
            st.markdown(f"""
            <div style="background:rgba(0,0,0,0.3);border-radius:10px;padding:14px 18px;
                        margin-top:12px;border:1px solid rgba(255,215,0,0.3)">
                <div style="font-size:0.76rem;color:{ACC};font-weight:600;margin-bottom:8px">
                    ✓ Link generated for <strong>{lbl}</strong>
                </div>
                <div style="font-size:0.8rem;color:rgba(255,255,255,0.7)">Share this URL with students:</div>
            </div>""", unsafe_allow_html=True)
            st.code(f"https://sxptkiopucmjsnzgpv4ekh.streamlit.app/?token={tok}")

    st.markdown('<hr style="margin:32px 0 20px">', unsafe_allow_html=True)
    db = get_db()
    all_responses = list(db.responses.find({}, PROJ))
    resp_counts = {}
    for r in all_responses:
        resp_counts[r["link_id"]] = resp_counts.get(r["link_id"], 0) + 1
    recent = sorted(db.semester_links.find({}, PROJ), key=lambda x: x["created_at"], reverse=True)[:6]

    if recent:
        st.markdown('<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px">Recent survey links</div>',
                    unsafe_allow_html=True)
        for i in range(0, len(recent), 2):
            cols = st.columns(2)
            for j, row in enumerate(recent[i:i+2]):
                with cols[j]:
                    rc = resp_counts.get(row["id"], 0)
                    st.markdown(f"""
                    <div style="background:rgba(255,255,255,0.12);border-radius:12px;
                                padding:16px 20px;margin-bottom:10px;
                                border:1px solid rgba(255,255,255,0.18)">
                        <div style="font-weight:700;font-size:1rem;color:white">{row['label']}</div>
                        <div style="font-size:0.78rem;color:rgba(255,255,255,0.55);margin-top:6px">
                            {rc} response(s) &nbsp;·&nbsp; token:
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

    sc1, _, sc2 = st.columns([2, 1, 2])
    with sc1:
        st.markdown('<div style="font-size:0.82rem;font-weight:700;color:white;margin-bottom:8px">Sort by</div>',
                    unsafe_allow_html=True)
        sort_v = st.radio("_sb", ["Year and Semester", "Subjects"],
                          index=0 if st.session_state.sort_by == "semester" else 1,
                          key="sort_radio", label_visibility="hidden")
        st.session_state.sort_by = "semester" if "Semester" in sort_v else "subject"
    with sc2:
        st.markdown('<div style="font-size:0.82rem;font-weight:700;color:white;margin-bottom:8px">Order</div>',
                    unsafe_allow_html=True)
        ord_v = st.radio("_ob", ["Ascending", "Descending"],
                         index=0 if st.session_state.sort_order == "asc" else 1,
                         key="order_radio", label_visibility="hidden")
        st.session_state.sort_order = "asc" if ord_v == "Ascending" else "desc"

    st.markdown("<br>", unsafe_allow_html=True)
    db   = get_db()
    desc = (st.session_state.sort_order == "desc")

    if st.session_state.sort_by == "semester":
        all_responses = list(db.responses.find({}, PROJ))
        resp_counts = {}
        for r in all_responses:
            resp_counts[r["link_id"]] = resp_counts.get(r["link_id"], 0) + 1
        rows = sorted(db.semester_links.find({}, PROJ), key=lambda x: x["label"], reverse=desc)
        if not rows:
            st.info("No survey links yet. Generate one from Admin home.")
            return
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for j, row in enumerate(rows[i:i+2]):
                with cols[j]:
                    st.markdown('<div class="pill-btn">', unsafe_allow_html=True)
                    cnt = resp_counts.get(row["id"], 0)
                    lbl = f"{row['label'].upper()}  ({cnt} RESPONSES)"
                    if st.button(lbl, key=f"s_{row['id']}", use_container_width=True):
                        st.session_state.drill_link_id = row["id"]
                        st.session_state.admin_view = "detail_semester"
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
    else:
        all_responses = list(db.responses.find({}, PROJ))
        subj_counts = {}
        for r in all_responses:
            if r.get("subject_name"):
                subj_counts[r["subject_name"]] = subj_counts.get(r["subject_name"], 0) + 1
        rows = sorted([{"subject_name": k, "cnt": v} for k, v in subj_counts.items()],
                      key=lambda x: x["subject_name"], reverse=desc)
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

    link_id   = st.session_state.drill_link_id
    db        = get_db()
    link      = db.semester_links.find_one({"id": link_id}, PROJ)
    responses = sorted(db.responses.find({"link_id": link_id}, PROJ),
                       key=lambda x: x["submitted_at"], reverse=True)
    questions = sorted(db.questions.find({}, PROJ), key=lambda x: x["order_num"])

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
    unique_s = len(set(r["subject_name"] for r in responses if r.get("subject_name")))
    c3.metric("Subjects", unique_s)

    if not responses:
        st.info("No responses yet."); return

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown('<div style="font-weight:700;color:white;font-size:0.95rem;margin-bottom:12px">Responses by subject</div>',
                unsafe_allow_html=True)
    sc = {}
    for r in responses:
        s = r.get("subject_name") or "Not specified"
        sc[s] = sc.get(s, 0) + 1
    if sc:
        df_sc = pd.DataFrame(sc.items(), columns=["Subject","Count"]).sort_values("Count", ascending=False)
        st.bar_chart(df_sc.set_index("Subject"))

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(f'<div style="font-weight:700;color:white;font-size:0.95rem;margin-bottom:12px">{len(responses)} Individual Responses</div>',
                unsafe_allow_html=True)

    for i, r in enumerate(responses):
        try: ans = json.loads(r["answers_json"])
        except: ans = {}
        subj = r.get("subject_name") or "Unknown"
        date = r["submitted_at"][:10] if r.get("submitted_at") else "—"
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

    st.markdown('<hr style="margin:20px 0">', unsafe_allow_html=True)
    rows_exp = []
    for r in responses:
        rd = {"Semester": link["label"], "Subject": r.get("subject_name"), "Date": r.get("submitted_at")}
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

    subj      = st.session_state.drill_subject
    db        = get_db()
    link_map  = {l["id"]: l["label"] for l in db.semester_links.find({}, PROJ)}
    responses = sorted(db.responses.find({"subject_name": subj}, PROJ),
                       key=lambda x: x["submitted_at"], reverse=True)
    for r in responses:
        r["sem_label"] = link_map.get(r["link_id"], "Unknown")
    questions = sorted(db.questions.find({}, PROJ), key=lambda x: x["order_num"])

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

    db        = get_db()
    questions = sorted(db.questions.find({"active": 1}, PROJ), key=lambda x: x["order_num"])
    subjects  = sorted(db.subjects.find({"active": 1}, PROJ), key=lambda x: x["name"])

    TYPE_OPTS   = ["dropdown","text","rating","yes_no"]
    TYPE_LABELS = ["Dropdown ▼","Text","Rating (1-5)","Yes / No"]
    TYPE_MAP    = dict(zip(TYPE_OPTS, TYPE_LABELS))
    TYPE_REV    = dict(zip(TYPE_LABELS, TYPE_OPTS))

    h0, h1, h2, h3, h4 = st.columns([0.5, 4, 2, 1.5, 1.2])
    for txt, col in [("No.", h0), ("Question", h1), ("Type", h2), ("AI Check", h3), ("Remove", h4)]:
        col.markdown(
            f'<div style="font-size:0.78rem;font-weight:700;color:rgba(255,255,255,0.55);' 
            f'padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.2)">{txt}</div>',
            unsafe_allow_html=True)

    st.markdown("")

    for i, q in enumerate(questions):
        c0, c1, c2, c3, c4 = st.columns([0.5, 4, 2, 1.5, 1.2])
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
            if q["question_type"] == "text":
                st.toggle("🤖", value=bool(q.get("ai_moderated", 0)),
                          key=f"qai_{q['id']}", help="Enable AI moderation for this answer")
            else:
                st.markdown('<div style="padding:14px 0;font-size:0.8rem;color:rgba(255,255,255,0.25)">—</div>',
                            unsafe_allow_html=True)
        with c4:
            st.markdown('<div class="rem-btn">', unsafe_allow_html=True)
            if st.button("−", key=f"rm_{q['id']}"):
                get_db().questions.update_one({"id": q["id"]}, {"$set": {"active": 0}})
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _, sc, _ = st.columns([1, 2, 1])
    with sc:
        st.markdown('<div class="save-btn">', unsafe_allow_html=True)
        if st.button("💾 SAVE ALL CHANGES", use_container_width=True, key="save_all"):
            db2 = get_db()
            for q in questions:
                nt  = st.session_state.get(f"qt_{q['id']}", q["question_text"])
                nl  = st.session_state.get(f"qtp_{q['id']}", TYPE_MAP.get(q["question_type"]))
                ntp = TYPE_REV.get(nl, q["question_type"])
                ai  = 1 if (ntp == "text" and st.session_state.get(f"qai_{q['id']}", False)) else 0
                db2.questions.update_one(
                    {"id": q["id"]},
                    {"$set": {"question_text": nt, "question_type": ntp, "ai_moderated": ai}}
                )
            st.success("Saved!")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.82rem;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:10px">Add new question</div>',
                unsafe_allow_html=True)

    na0, na1, na2, na3, na4 = st.columns([0.5, 4, 2, 1.5, 1.2])
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
        if nq_type_lbl == "Text":
            nq_ai = st.toggle("🤖", value=False, key="nq_ai",
                              help="Enable AI moderation for this answer")
        else:
            nq_ai = False
            st.markdown('<div style="padding:14px 0;font-size:0.8rem;color:rgba(255,255,255,0.25)">—</div>',
                        unsafe_allow_html=True)
    with na4:
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("＋", key="add_q"):
            if nq_text.strip():
                db2  = get_db()
                qs   = list(db2.questions.find({}, PROJ))
                mo   = max((q["order_num"] for q in qs), default=0)
                qid  = next_id("questions")
                ntp  = TYPE_REV.get(nq_type_lbl, "text")
                db2.questions.insert_one({
                    "id": qid, "question_text": nq_text.strip(),
                    "question_type": ntp, "order_num": mo + 1, "active": 1,
                    "ai_moderated": 1 if (ntp == "text" and nq_ai) else 0
                })
                st.rerun()
            else:
                st.warning("Enter question text.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<hr style="margin:28px 0">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px">Subjects (for Dropdown question)</div>',
                unsafe_allow_html=True)

    for subj in subjects:
        s1, s2 = st.columns([7, 1.5])
        with s1:
            st.markdown(
                f'<div style="padding:10px 0;font-size:0.9rem;color:rgba(255,255,255,0.85)">• {subj["name"]}</div>',
                unsafe_allow_html=True)
        with s2:
            st.markdown('<div class="rem-btn">', unsafe_allow_html=True)
            if st.button("−", key=f"rs_{subj['id']}"):
                get_db().subjects.update_one({"id": subj["id"]}, {"$set": {"active": 0}})
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
                db2      = get_db()
                existing = db2.subjects.find_one({"name": ns.strip()}, PROJ)
                if existing:
                    db2.subjects.update_one({"name": ns.strip()}, {"$set": {"active": 1}})
                else:
                    sid = next_id("subjects")
                    db2.subjects.insert_one({"id": sid, "name": ns.strip(), "active": 1})
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
# Seed DB once per session — runs after Streamlit is fully initialised
if not st.session_state.get("_db_ready"):
    ensure_defaults()
    st.session_state["_db_ready"] = True

if TOKEN:
    page_student(TOKEN)
elif ADMIN_PARAM is not None or st.session_state.admin_logged_in:
    if st.session_state.admin_logged_in:
        page_admin()
    else:
        page_login()
else:
    page_landing()
