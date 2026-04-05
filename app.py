import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from google import genai
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from utils.security import hpw
from db.init_db import init_db, seed_payload

DATA_PATH = Path("CourseVoice.json")

# ============================================================================
# MONGODB IMPORTS
# ============================================================================

MONGO_IMPORT_OK = False
MONGO_IMPORT_ERROR = None

try:
    from db.mongo import get_database
    from db.db_collections import (
        admins_col,
        subjects_col,
        questions_col,
        semester_links_col,
        responses_col,
        counters_col,
    )
    MONGO_IMPORT_OK = True
except Exception as e:
    MONGO_IMPORT_OK = False
    MONGO_IMPORT_ERROR = f"{type(e).__name__}: {e}"

# ============================================================================
# GEMINI
# ============================================================================

GEMINI_MODEL = "gemini-2.5-flash"
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


def moderate_answer(question_text, answer_text):
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
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if parsed.get("acceptable", True):
            return True, None, None
        return (
            False,
            parsed.get("reason", "Please provide a more constructive answer."),
            parsed.get("tip", ""),
        )
    except Exception:
        return True, None, None


def check_llm_status():
    try:
        start = time.time()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents="Reply with only the word: OK",
        )
        elapsed = int((time.time() - start) * 1000)
        return True, elapsed, response.text.strip()
    except Exception as e:
        return False, None, str(e)


def check_db_status():
    try:
        start = time.time()

        if not MONGO_IMPORT_OK:
            return {
                "online": False,
                "ms": None,
                "msg": MONGO_IMPORT_ERROR or "Mongo imports failed",
                "details": {
                    "import_ok": False,
                    "connected": False,
                    "init_ok": False,
                    "mode": "json_fallback",
                    "db_name": None,
                    "collections": [],
                    "error": MONGO_IMPORT_ERROR,
                },
            }

        db = get_database()
        db.command("ping")
        bootstrap_db()

        elapsed = int((time.time() - start) * 1000)

        details = {
            "import_ok": True,
            "connected": True,
            "init_ok": True,
            "mode": "mongodb",
            "db_name": getattr(db, "name", None),
            "collections": db.list_collection_names(),
            "error": None,
        }

        return {
            "online": True,
            "ms": elapsed,
            "msg": "MongoDB connection healthy",
            "details": details,
        }

    except Exception as e:
        return {
            "online": False,
            "ms": None,
            "msg": f"{type(e).__name__}: {e}",
            "details": {
                "import_ok": MONGO_IMPORT_OK,
                "connected": False,
                "init_ok": False,
                "mode": "json_fallback",
                "db_name": None,
                "collections": [],
                "error": f"{type(e).__name__}: {e}",
            },
        }


@st.cache_data(ttl=60, show_spinner=False)
def summarize_survey_responses_with_gemini(link_label: str, questions_json: str, responses_json: str):
    try:
        questions = json.loads(questions_json)
        responses = json.loads(responses_json)

        if not responses:
            return "No responses available to summarize."

        question_map = {str(q["id"]): q["question_text"] for q in questions}

        lines = []
        for idx, response in enumerate(responses[:12], start=1):
            subject_name = response.get("subject_name") or "Unknown"
            submitted_at = response.get("submitted_at") or "Unknown date"
            answers = response.get("answers", {})

            lines.append(f"Response {idx} | Subject: {subject_name} | Date: {submitted_at}")
            for qid, answer in answers.items():
                qtext = question_map.get(str(qid), f"Question {qid}")
                lines.append(f"- {qtext}: {answer}")
            lines.append("")

        prompt = f"""You are summarizing course survey responses for an admin dashboard.

Survey label: {link_label}

Create a very short, simple summary in 3 bullet points max.
Focus on:
- overall sentiment
- recurring positive themes
- any obvious difficulty or improvement pattern

Be factual and concise.
Do not invent missing information.
Do not mention that you are an AI.

Survey responses:
{chr(10).join(lines)}

Return plain text only.
"""

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()

    except Exception as e:
        return f"Summary unavailable: {type(e).__name__}: {e}"


# ============================================================================
# STREAMLIT CONFIG
# ============================================================================

st.set_page_config(
    page_title="CourseVoice",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================================
# SESSION STATE
# ============================================================================

SESSION_DEFAULTS = {
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
    "llm_status": None,
    "db_status": None,
    "admin_notice": None,
}

for k, v in SESSION_DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================================
# HELPERS
# ============================================================================


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalize_doc(doc):
    if not doc:
        return None

    out = dict(doc)
    oid = out.get("_id")

    # keep the original Mongo id available in string form
    out["mongo_oid"] = str(oid) if oid is not None else None

    # make the _id itself JSON-safe too
    if oid is not None:
        out["_id"] = str(oid)

    return out

def normalize_docs(docs):
    return [normalize_doc(d) for d in docs]


def parse_answers(response_doc):
    raw = response_doc.get("answers_json")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def safe_int(v):
    try:
        return int(v)
    except Exception:
        return None


# ============================================================================
# MONGO STATUS / BOOTSTRAP
# ============================================================================


@st.cache_resource(show_spinner=False)
def bootstrap_db():
    if not MONGO_IMPORT_OK:
        return False

    db = get_database()
    db.command("ping")
    init_db()

    admins_col().create_index("username", unique=True)

    subjects_col().create_index([("active", ASCENDING), ("name", ASCENDING)])
    subjects_col().create_index("id", unique=True)

    questions_col().create_index([("active", ASCENDING), ("order_num", ASCENDING)])
    questions_col().create_index("id", unique=True)

    semester_links_col().create_index("id", unique=True)
    semester_links_col().create_index("token", unique=True)
    semester_links_col().create_index([("created_at", DESCENDING)])

    responses_col().create_index("id", unique=True)
    responses_col().create_index([("link_id", ASCENDING), ("submitted_at", DESCENDING)])
    responses_col().create_index([("subject_name", ASCENDING), ("submitted_at", DESCENDING)])

    return True


@st.cache_data(ttl=20, show_spinner=False)
def get_mongo_status():
    status = {
        "import_ok": MONGO_IMPORT_OK,
        "connected": False,
        "init_ok": False,
        "mode": "json_fallback",
        "error": None,
        "db_name": None,
        "collections": [],
    }

    if not MONGO_IMPORT_OK:
        status["error"] = MONGO_IMPORT_ERROR
        return status

    try:
        db = get_database()
        db.command("ping")
        bootstrap_db()
        status["connected"] = True
        status["init_ok"] = True
        status["mode"] = "mongodb"
        status["db_name"] = getattr(db, "name", None)
        status["collections"] = db.list_collection_names()
        return status
    except Exception as e:
        status["error"] = f"{type(e).__name__}: {e}"
        return status


@st.cache_data(ttl=20, show_spinner=False)
def mongo_available():
    return get_mongo_status()["mode"] == "mongodb"


def clear_runtime_caches():
    # Only clear functions that are ACTUALLY cached

    get_mongo_status.clear()
    mongo_available.clear()

    get_admin_by_username.clear()
    get_link_by_token_cached.clear()
    get_active_subjects.clear()
    get_active_questions.clear()
    get_recent_links_with_counts.clear()
    get_results_index_semester.clear()
    get_results_index_subject.clear()
    get_semester_detail_bundle.clear()
    get_subject_detail_bundle.clear()

    summarize_survey_responses_with_gemini.clear()

MONGO_STATUS = get_mongo_status()
MONGO_STATUS_MSG = None if MONGO_STATUS["mode"] == "mongodb" else f"Mongo fallback active. Reason: {MONGO_STATUS['error']}"

# ============================================================================
# JSON FALLBACK
# ============================================================================


def _ensure_ids_exist(data):
    data.setdefault("_next_ids", {})
    for name, start in {
        "subjects": 9,
        "questions": 5,
        "semester_links": 1,
        "responses": 1,
    }.items():
        data["_next_ids"].setdefault(name, start)
    return data


def _save_json(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_json():
    try:
        if DATA_PATH.exists():
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                return _ensure_ids_exist(json.load(f))

        data = seed_payload()
        _save_json(data)
        return _ensure_ids_exist(data)
    except Exception as e:
        st.error(f"JSON fallback failed: {type(e).__name__}: {e}")
        raise


def load_data():
    return _load_json()


def save_data(data):
    _save_json(_ensure_ids_exist(data))
    clear_runtime_caches()


# ============================================================================
# LOW-LEVEL MONGO HELPERS
# ============================================================================


def next_counter_value(name: str) -> int:
    doc = counters_col().find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )
    if doc and "seq" in doc:
        return int(doc["seq"])

    seeded = {
        "subjects": 9,
        "questions": 5,
        "semester_links": 1,
        "responses": 1,
    }.get(name, 1)
    counters_col().update_one({"_id": name}, {"$setOnInsert": {"seq": seeded + 1}}, upsert=True)
    return seeded


@st.cache_data(ttl=60, show_spinner=False)
def get_admin_by_username(username: str):
    if mongo_available():
        bootstrap_db()
        doc = admins_col().find_one({"username": username})
        return normalize_doc(doc)

    data = load_data()
    row = next((a for a in data["admins"] if a["username"] == username), None)
    if not row:
        return None
    out = dict(row)
    out["mongo_oid"] = None
    return out


@st.cache_data(ttl=60, show_spinner=False)
def get_link_by_token_cached(token: str):
    if mongo_available():
        bootstrap_db()
        return normalize_doc(semester_links_col().find_one({"token": token}))

    data = load_data()
    row = next((l for l in data["semester_links"] if l["token"] == token), None)
    if not row:
        return None
    out = dict(row)
    out["mongo_oid"] = None
    return out


def get_link_by_token(token: str):
    return get_link_by_token_cached(token)


@st.cache_data(ttl=60, show_spinner=False)
def get_active_subjects():
    if mongo_available():
        bootstrap_db()
        docs = subjects_col().find(
            {"active": 1},
            {"_id": 1, "id": 1, "name": 1, "active": 1},
        ).sort("name", ASCENDING)
        return normalize_docs(list(docs))

    data = load_data()
    return [dict(s, mongo_oid=None) for s in sorted(data["subjects"], key=lambda x: x["name"]) if s["active"]]


@st.cache_data(ttl=60, show_spinner=False)
def get_active_questions():
    if mongo_available():
        bootstrap_db()
        docs = questions_col().find(
            {"active": 1},
            {
                "_id": 1,
                "id": 1,
                "question_text": 1,
                "question_type": 1,
                "order_num": 1,
                "active": 1,
                "ai_moderated": 1,
            },
        ).sort("order_num", ASCENDING)
        return normalize_docs(list(docs))

    data = load_data()
    return [dict(q, mongo_oid=None) for q in sorted(data["questions"], key=lambda x: x["order_num"]) if q["active"]]


@st.cache_data(ttl=30, show_spinner=False)
def get_recent_links_with_counts(limit: int = 6):
    if mongo_available():
        bootstrap_db()
        pipeline = [
            {
                "$lookup": {
                    "from": "responses",
                    "localField": "id",
                    "foreignField": "link_id",
                    "as": "responses_join",
                }
            },
            {
                "$addFields": {
                    "response_count": {"$size": "$responses_join"}
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "id": 1,
                    "label": 1,
                    "token": 1,
                    "created_at": 1,
                    "response_count": 1,
                }
            },
            {"$sort": {"created_at": -1}},
            {"$limit": limit},
        ]
        docs = list(semester_links_col().aggregate(pipeline))
        return normalize_docs(docs)

    data = load_data()
    counts = {}
    for r in data["responses"]:
        counts[r["link_id"]] = counts.get(r["link_id"], 0) + 1
    rows = sorted(data["semester_links"], key=lambda x: x["created_at"], reverse=True)[:limit]
    return [dict(r, mongo_oid=None, response_count=counts.get(r["id"], 0)) for r in rows]


@st.cache_data(ttl=30, show_spinner=False)
def get_results_index_semester(sort_order: str):
    desc = sort_order == "desc"

    if mongo_available():
        bootstrap_db()
        pipeline = [
            {
                "$lookup": {
                    "from": "responses",
                    "localField": "id",
                    "foreignField": "link_id",
                    "as": "responses_join",
                }
            },
            {
                "$addFields": {
                    "response_count": {"$size": "$responses_join"}
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "id": 1,
                    "label": 1,
                    "token": 1,
                    "created_at": 1,
                    "response_count": 1,
                }
            },
            {"$sort": {"label": -1 if desc else 1}},
        ]
        docs = list(semester_links_col().aggregate(pipeline))
        return normalize_docs(docs)

    data = load_data()
    counts = {}
    for r in data["responses"]:
        counts[r["link_id"]] = counts.get(r["link_id"], 0) + 1
    rows = sorted(data["semester_links"], key=lambda x: x["label"], reverse=desc)
    return [dict(r, mongo_oid=None, response_count=counts.get(r["id"], 0)) for r in rows]


@st.cache_data(ttl=30, show_spinner=False)
def get_results_index_subject(sort_order: str):
    desc = sort_order == "desc"

    if mongo_available():
        bootstrap_db()
        pipeline = [
            {"$match": {"subject_name": {"$ne": None, "$exists": True}}},
            {"$group": {"_id": "$subject_name", "cnt": {"$sum": 1}}},
            {"$project": {"_id": 0, "subject_name": "$_id", "cnt": 1}},
            {"$sort": {"subject_name": -1 if desc else 1}},
        ]
        return list(responses_col().aggregate(pipeline))

    data = load_data()
    counts = {}
    for r in data["responses"]:
        if r.get("subject_name"):
            counts[r["subject_name"]] = counts.get(r["subject_name"], 0) + 1
    rows = [{"subject_name": k, "cnt": v} for k, v in counts.items()]
    return sorted(rows, key=lambda x: x["subject_name"], reverse=desc)


@st.cache_data(ttl=30, show_spinner=False)
def get_semester_detail_bundle(link_id: int):
    if mongo_available():
        bootstrap_db()

        link = normalize_doc(
            semester_links_col().find_one(
                {"id": link_id},
                {"_id": 1, "id": 1, "label": 1, "token": 1, "created_at": 1},
            )
        )

        questions = normalize_docs(
            list(
                questions_col().find(
                    {"active": 1},
                    {
                        "_id": 1,
                        "id": 1,
                        "question_text": 1,
                        "question_type": 1,
                        "order_num": 1,
                        "ai_moderated": 1,
                        "active": 1,
                    },
                ).sort("order_num", ASCENDING)
            )
        )

        responses = normalize_docs(
            list(
                responses_col().find(
                    {"link_id": link_id},
                    {"_id": 1, "id": 1, "link_id": 1, "subject_name": 1, "answers_json": 1, "submitted_at": 1},
                ).sort("submitted_at", DESCENDING)
            )
        )
        return link, questions, responses

    data = load_data()
    link = next((l for l in data["semester_links"] if l["id"] == link_id), None)
    if link:
        link = dict(link, mongo_oid=None)
    questions = [dict(q, mongo_oid=None) for q in sorted(data["questions"], key=lambda x: x["order_num"])]
    responses = [
        dict(r, mongo_oid=None)
        for r in sorted(
            [r for r in data["responses"] if r["link_id"] == link_id],
            key=lambda x: x["submitted_at"],
            reverse=True,
        )
    ]
    return link, questions, responses


@st.cache_data(ttl=30, show_spinner=False)
def get_subject_detail_bundle(subject_name: str):
    if mongo_available():
        bootstrap_db()

        questions = normalize_docs(
            list(
                questions_col().find(
                    {"active": 1},
                    {
                        "_id": 1,
                        "id": 1,
                        "question_text": 1,
                        "question_type": 1,
                        "order_num": 1,
                        "ai_moderated": 1,
                        "active": 1,
                    },
                ).sort("order_num", ASCENDING)
            )
        )

        links = normalize_docs(
            list(
                semester_links_col().find(
                    {},
                    {"_id": 1, "id": 1, "label": 1},
                )
            )
        )
        link_map = {l["id"]: l for l in links}

        responses = normalize_docs(
            list(
                responses_col().find(
                    {"subject_name": subject_name},
                    {"_id": 1, "id": 1, "link_id": 1, "subject_name": 1, "answers_json": 1, "submitted_at": 1},
                ).sort("submitted_at", DESCENDING)
            )
        )

        return questions, link_map, responses

    data = load_data()
    questions = [dict(q, mongo_oid=None) for q in sorted(data["questions"], key=lambda x: x["order_num"])]
    link_map = {l["id"]: dict(l, mongo_oid=None) for l in data["semester_links"]}
    responses = [
        dict(r, mongo_oid=None)
        for r in sorted(
            [r for r in data["responses"] if r.get("subject_name") == subject_name],
            key=lambda x: x["submitted_at"],
            reverse=True,
        )
    ]
    return questions, link_map, responses


# ============================================================================
# WRITE HELPERS
# ============================================================================


def create_response(link_id: int, subject_name: str, answers: dict):
    if mongo_available():
        bootstrap_db()
        new_id = next_counter_value("responses")
        responses_col().insert_one(
            {
                "id": new_id,
                "link_id": link_id,
                "subject_name": subject_name,
                "answers_json": json.dumps(answers),
                "submitted_at": now_str(),
            }
        )
        clear_runtime_caches()
        return new_id

    data = load_data()
    data = _ensure_ids_exist(data)
    rid = data["_next_ids"]["responses"]
    data["_next_ids"]["responses"] += 1
    data["responses"].append(
        {
            "id": rid,
            "link_id": link_id,
            "subject_name": subject_name,
            "answers_json": json.dumps(answers),
            "submitted_at": now_str(),
        }
    )
    save_data(data)
    return rid


def create_semester_link(label: str):
    if mongo_available():
        bootstrap_db()
        new_id = next_counter_value("semester_links")
        token = uuid.uuid4().hex[:8].upper()
        semester_links_col().insert_one(
            {
                "id": new_id,
                "label": label.strip(),
                "token": token,
                "created_at": now_str(),
            }
        )
        clear_runtime_caches()
        return {"id": new_id, "label": label.strip(), "token": token}

    data = load_data()
    data = _ensure_ids_exist(data)
    new_id = data["_next_ids"]["semester_links"]
    data["_next_ids"]["semester_links"] += 1
    token = uuid.uuid4().hex[:8].upper()
    data["semester_links"].append(
        {
            "id": new_id,
            "label": label.strip(),
            "token": token,
            "created_at": now_str(),
        }
    )
    save_data(data)
    return {"id": new_id, "label": label.strip(), "token": token}


def soft_remove_question(question_id: int):
    if mongo_available():
        bootstrap_db()
        questions_col().update_one({"id": question_id}, {"$set": {"active": 0}})
        clear_runtime_caches()
        return

    data = load_data()
    for q in data["questions"]:
        if q["id"] == question_id:
            q["active"] = 0
    save_data(data)


def save_questions_bulk(question_updates: list):
    if mongo_available():
        bootstrap_db()
        for q in question_updates:
            questions_col().update_one(
                {"id": q["id"]},
                {
                    "$set": {
                        "question_text": q["question_text"],
                        "question_type": q["question_type"],
                        "ai_moderated": q["ai_moderated"],
                    }
                },
            )
        clear_runtime_caches()
        return

    data = load_data()
    by_id = {q["id"]: q for q in question_updates}
    for q in data["questions"]:
        if q["id"] in by_id:
            q["question_text"] = by_id[q["id"]]["question_text"]
            q["question_type"] = by_id[q["id"]]["question_type"]
            q["ai_moderated"] = by_id[q["id"]]["ai_moderated"]
    save_data(data)


def add_question(question_text: str, question_type: str, ai_moderated: int):
    if mongo_available():
        bootstrap_db()

        last = questions_col().find_one(sort=[("order_num", DESCENDING)])
        next_order = (last.get("order_num", 0) if last else 0) + 1
        new_id = next_counter_value("questions")

        questions_col().insert_one(
            {
                "id": new_id,
                "question_text": question_text.strip(),
                "question_type": question_type,
                "order_num": next_order,
                "active": 1,
                "ai_moderated": ai_moderated,
            }
        )
        clear_runtime_caches()
        return new_id

    data = load_data()
    data = _ensure_ids_exist(data)
    new_id = data["_next_ids"]["questions"]
    data["_next_ids"]["questions"] += 1
    mo = max((q["order_num"] for q in data["questions"]), default=0)
    data["questions"].append(
        {
            "id": new_id,
            "question_text": question_text.strip(),
            "question_type": question_type,
            "order_num": mo + 1,
            "active": 1,
            "ai_moderated": ai_moderated,
        }
    )
    save_data(data)
    return new_id


def soft_remove_subject(subject_id: int):
    if mongo_available():
        bootstrap_db()
        subjects_col().update_one({"id": subject_id}, {"$set": {"active": 0}})
        clear_runtime_caches()
        return

    data = load_data()
    for s in data["subjects"]:
        if s["id"] == subject_id:
            s["active"] = 0
    save_data(data)


def add_or_reactivate_subject(subject_name: str):
    clean_name = subject_name.strip()

    if mongo_available():
        bootstrap_db()
        existing = subjects_col().find_one({"name": clean_name})
        if existing:
            subjects_col().update_one({"name": clean_name}, {"$set": {"active": 1}})
            clear_runtime_caches()
            return existing.get("id")

        new_id = next_counter_value("subjects")
        subjects_col().insert_one({"id": new_id, "name": clean_name, "active": 1})
        clear_runtime_caches()
        return new_id

    data = load_data()
    existing = next((s for s in data["subjects"] if s["name"] == clean_name), None)
    if existing:
        existing["active"] = 1
        save_data(data)
        return existing["id"]

    data = _ensure_ids_exist(data)
    new_id = data["_next_ids"]["subjects"]
    data["_next_ids"]["subjects"] += 1
    data["subjects"].append({"id": new_id, "name": clean_name, "active": 1})
    save_data(data)
    return new_id


# ============================================================================
# NAV / STATE HELPERS
# ============================================================================


def go_admin(view, *, drill_link_id=None, drill_subject=None):
    st.session_state.admin_view = view
    st.session_state.drill_link_id = drill_link_id
    st.session_state.drill_subject = drill_subject
    st.rerun()


def logout_admin():
    st.session_state.admin_logged_in = False
    st.session_state.admin_user = ""
    st.session_state.admin_view = "home"
    st.session_state.drill_link_id = None
    st.session_state.drill_subject = None
    st.session_state.gen_token = None
    st.session_state.llm_status = None
    st.session_state.db_status = None
    st.session_state.admin_notice = None
    st.query_params.clear()
    st.rerun()


# ============================================================================
# ROUTING / THEMING
# ============================================================================

TOKEN = st.query_params.get("token", None)
ADMIN_PARAM = st.query_params.get("admin", None)
DARK = st.session_state.dark_mode
IS_ADMIN = (ADMIN_PARAM is not None or st.session_state.admin_logged_in) and TOKEN is None
ACC = "#FFD700"

if IS_ADMIN:
    BG = "#4a6295"
    FG = "#ffffff"
    INP = "rgba(30,45,80,0.55)"
    BDR = "rgba(255,215,0,0.85)"
    MUTED = "rgba(255,255,255,0.55)"
    CARD = "rgba(255,255,255,0.13)"
elif DARK:
    BG = "#242424"
    FG = "#e2e2e2"
    INP = "#2e2e2e"
    BDR = ACC
    MUTED = "#888888"
    CARD = "#2c2c2c"
else:
    BG = "#e8e4d8"
    FG = "#1a1a1a"
    INP = "#ffffff"
    BDR = "#1a1a1a"
    MUTED = "#777777"
    CARD = "#ffffff"

if IS_ADMIN:
    BTN_BG = "transparent"
    BTN_FG = ACC
    RADIO_BG = "#1a1a1a"
elif DARK:
    BTN_BG = "#1a1a1a"
    BTN_FG = "#ffffff"
    RADIO_BG = "#1a1a1a"
else:
    BTN_BG = INP
    BTN_FG = "#1a1a1a"
    RADIO_BG = "#555555"

st.markdown(
    f"""
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

input[placeholder="Enter the year and semester (e.g., 2025 Semester 1)"] {{
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}}
input[placeholder="Enter the year and semester (e.g., 2025 Semester 1)"]:focus {{
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}}
input[placeholder="Enter the year and semester (e.g. 2025 Semester 1)"] {{
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}}
input[placeholder="Enter the year and semester (e.g. 2025 Semester 1)"]:focus {{
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
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

div[data-baseweb="popover"],
div[data-baseweb="popover"] ul,
div[data-baseweb="popover"] li {{
    background: {INP} !important;
    color: {FG} !important;
}}
div[data-baseweb="popover"] li:hover {{
    background: {BDR} !important;
    color: #111 !important;
}}
div[data-baseweb="popover"] li[aria-selected="true"] {{
    background: {ACC} !important;
    color: #111 !important;
}}

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

/* Remove default Streamlit form container outline */
[data-testid="stForm"] {{
    border: none !important;
    padding: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
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
""",
    unsafe_allow_html=True,
)

# ============================================================================
# ADMIN HEADER
# ============================================================================


def render_admin_header():
    c1, _, c3 = st.columns([4, 3, 2])
    with c1:
        st.markdown(
            f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.6)">'
            f'Logged in as <strong style="color:white">{st.session_state.admin_user}</strong></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
        if st.button("Logout", key="logout_btn"):
            logout_admin()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<hr style="margin:8px 0 20px">', unsafe_allow_html=True)

# ============================================================================
# STUDENT SURVEY
# ============================================================================


def page_student(token):
    _, tcol = st.columns([8, 2])
    with tcol:
        nd = st.toggle("🌙 Dark mode", value=DARK, key="dm_t")
        if nd != DARK:
            st.session_state.dark_mode = nd
            st.rerun()

    link = get_link_by_token(token)
    if not link:
        st.error("❌ Invalid or expired survey link.")
        return

    subjects = [s["name"] for s in get_active_subjects()]
    questions = get_active_questions()

    if st.session_state.submitted:
        _, cc, _ = st.columns([1, 3, 1])
        with cc:
            st.markdown(
                f"""
            <div style="text-align:center;padding:100px 0">
                <div style="font-size:3rem;margin-bottom:16px">🎉</div>
                <div style="font-size:1.8rem;font-weight:700;color:{FG}">Thank you!</div>
            </div>""",
                unsafe_allow_html=True,
            )
        _, bc, _ = st.columns([1, 4, 1])
        with bc:
            if st.button("Submit another response", use_container_width=True):
                st.session_state.submitted = False
                st.rerun()
        return

    st.markdown(
        f"""
    <div style="text-align:center;padding:18px 0 28px">
        <div style="font-size:0.68rem;letter-spacing:3.5px;text-transform:uppercase;
                    color:{MUTED};margin-bottom:10px;font-weight:600">{link['label']}</div>
        <div style="font-size:2.2rem;font-weight:800;color:{FG};letter-spacing:-0.5px">Course Feedback</div>
    </div>""",
        unsafe_allow_html=True,
    )

    if st.session_state.form_errors:
        for e in st.session_state.form_errors:
            if isinstance(e, dict):
                st.markdown(
                    f'<div style="background:#5c1a1a;border:1px solid #e74c3c;border-radius:8px;'
                    f'padding:12px 16px;margin:8px 0;color:#ff6b6b;font-size:0.88rem">'
                    f'⚠️ {e["msg"]}</div>',
                    unsafe_allow_html=True,
                )
                if e.get("tip"):
                    st.markdown(
                        f'<div style="background:#1a2f4a;border:1px solid #3a7bd5;border-radius:8px;'
                        f'padding:12px 16px;margin:4px 0 8px;color:#7eb8f7;font-size:0.88rem">'
                        f'💡 Tip: {e["tip"]}</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    f'<div style="background:#5c1a1a;border:1px solid #e74c3c;border-radius:8px;'
                    f'padding:12px 16px;margin:8px 0;color:#ff6b6b;font-size:0.88rem">'
                    f'⚠️ {e}</div>',
                    unsafe_allow_html=True,
                )
        st.session_state.form_errors = []

    with st.form("sf", clear_on_submit=False):
        for i, q in enumerate(questions):
            if i > 0:
                st.markdown(
                    '<hr style="border:none;border-top:1px solid rgba(128,128,128,0.25);margin:20px 0">',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div style="font-size:0.9rem;color:{FG};margin-bottom:12px;font-weight:400">'
                f'{q["question_text"]}</div>',
                unsafe_allow_html=True,
            )

            qt, qid = q["question_type"], q["id"]
            if qt == "dropdown":
                st.selectbox(
                    " ",
                    ["— Select a subject —"] + subjects,
                    label_visibility="collapsed",
                    key=f"q{qid}",
                )
            elif qt == "text":
                st.text_input(
                    " ",
                    placeholder="Type your answer here…",
                    label_visibility="collapsed",
                    key=f"q{qid}",
                )
            elif qt == "rating":
                st.radio(
                    " ",
                    [1, 2, 3, 4, 5],
                    index=None,
                    horizontal=True,
                    label_visibility="collapsed",
                    key=f"q{qid}",
                )
            elif qt == "yes_no":
                st.radio(
                    " ",
                    ["Yes", "No"],
                    index=None,
                    horizontal=True,
                    label_visibility="collapsed",
                    key=f"q{qid}",
                )

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
                            acceptable, reason, tip = moderate_answer(
                                q["question_text"],
                                str(v).strip(),
                            )
                        if not acceptable:
                            errors.append(
                                {
                                    "msg": f"Please revise your answer: {reason}",
                                    "tip": tip,
                                }
                            )
                elif q["question_type"] in ("rating", "yes_no") and v is None:
                    errors.append(f'Please answer: "{q["question_text"]}"')

                if q["question_type"] == "dropdown" and v and v != "— Select a subject —":
                    subj = v

            if errors:
                st.session_state.form_errors = errors
                st.rerun()
            else:
                create_response(link["id"], subj, ans)
                st.session_state.submitted = True
                st.rerun()

# ============================================================================
# LANDING
# ============================================================================


def page_landing():
    _, tc = st.columns([8, 2])
    with tc:
        nd = st.toggle("🌙 Dark mode", value=DARK, key="dm_land")
        if nd != DARK:
            st.session_state.dark_mode = nd
            st.rerun()

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            f"""
        <div style="text-align:center;padding:80px 0 40px">
            <div style="font-size:3rem;font-weight:800;color:{FG};letter-spacing:-2px">CourseVoice</div>
        </div>""",
            unsafe_allow_html=True,
        )

        _, bc, _ = st.columns([2, 1, 2])
        with bc:
            if st.button("🔐 Admin Login"):
                st.query_params["admin"] = "1"
                st.rerun()

        st.markdown(
            f"""
        <div style="text-align:center;margin-top:32px;font-size:0.85rem;color:{MUTED}">
            Are you a student? Use the survey link your instructor shared with you.
        </div>""",
            unsafe_allow_html=True,
        )

# ============================================================================
# ADMIN LOGIN
# ============================================================================


def page_login():
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            """
        <div style="text-align:center;padding:70px 0 36px">
            <div style="font-size:2.6rem;font-weight:800;color:white;letter-spacing:-1.5px">CourseVoice</div>
            <div style="font-size:0.88rem;color:rgba(255,255,255,0.6);margin-top:8px">Admin Portal</div>
        </div>""",
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            user = st.text_input("Username", placeholder="admin", key="login_username")
            pw = st.text_input("Password", type="password", placeholder="••••••••", key="login_password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            with st.spinner("Signing in..."):
                row = get_admin_by_username(user.strip())

            if row and row["password_hash"] == hpw(pw):
                st.session_state.admin_logged_in = True
                st.session_state.admin_user = row["username"]
                st.session_state.admin_view = "home"
                st.query_params["admin"] = "1"
                st.rerun()
            else:
                st.error("Invalid credentials.")

# ============================================================================
# ADMIN HOME
# ============================================================================


def page_admin_home():
    render_admin_header()

    if MONGO_STATUS_MSG:
        st.warning(MONGO_STATUS_MSG)

    st.markdown(
        """
    <div style="text-align:center;font-size:2.8rem;font-weight:800;color:white;
                letter-spacing:-1px;margin:0 0 36px">ADMIN VIEW</div>""",
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 3, 1])
    with col:
        st.markdown('<div class="admin-action">', unsafe_allow_html=True)
        if st.button("VIEW SURVEY RESULTS", use_container_width=True, key="go_results"):
            go_admin("results")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("ADD/EDIT SURVEY QUESTIONS", use_container_width=True, key="go_edit"):
            go_admin("edit")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<hr style="margin:28px 0 20px">', unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:12px;text-align:center">'
            "🤖 AI Connection Debug</div>",
            unsafe_allow_html=True,
        )

        if st.button("Check AI Connection", use_container_width=True, key="llm_check"):
            with st.spinner("Pinging Gemini…"):
                online, ms, msg = check_llm_status()
            st.session_state.llm_status = {"online": online, "ms": ms, "msg": msg}

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
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="background:rgba(92,26,26,0.6);border:1px solid #e74c3c;'
                    f'border-radius:10px;padding:14px 18px;margin-top:10px;text-align:center">'
                    f'<div style="font-size:1.1rem;color:#ff6b6b;font-weight:700">❌ Offline</div>'
                    f'<div style="font-size:0.78rem;color:rgba(255,100,100,0.8);margin-top:4px">'
                    f'{status["msg"]}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.markdown('<div style="margin-top:18px"></div>', unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:12px;text-align:center">'
            "🗄️ DB Connection Debug</div>",
            unsafe_allow_html=True,
        )

        if st.button("Check DB Connection", use_container_width=True, key="db_check"):
            with st.spinner("Pinging MongoDB…"):
                st.session_state.db_status = check_db_status()

        db_status = st.session_state.get("db_status")
        if db_status is not None:
            if db_status["online"]:
                details = db_status["details"]
                st.markdown(
                    f'<div style="background:rgba(39,174,96,0.18);border:1px solid #27ae60;'
                    f'border-radius:10px;padding:14px 18px;margin-top:10px;text-align:center">'
                    f'<div style="font-size:1.1rem;color:#2ecc71;font-weight:700">✅ Online</div>'
                    f'<div style="font-size:0.78rem;color:rgba(255,255,255,0.6);margin-top:4px">'
                    f'Responded in <strong style="color:white">{db_status["ms"]} ms</strong>'
                    f'<br>Database: <strong style="color:white">{details["db_name"] or "—"}</strong>'
                    f'<br>Collections: <strong style="color:white">{len(details["collections"])}</strong></div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.markdown('<div style="margin-top:12px"></div>', unsafe_allow_html=True)
                with st.expander("View DB Details", expanded=False):
                    st.write("Import OK:", details["import_ok"])
                    st.write("Connected:", details["connected"])
                    st.write("Init OK:", details["init_ok"])
                    st.write("Mode:", details["mode"])
                    st.write("Database:", details["db_name"])
                    st.write("Collections:", details["collections"])
                    st.write("Error:", details["error"])
            else:
                details = db_status["details"]
                st.markdown(
                    f'<div style="background:rgba(92,26,26,0.6);border:1px solid #e74c3c;'
                    f'border-radius:10px;padding:14px 18px;margin-top:10px;text-align:center">'
                    f'<div style="font-size:1.1rem;color:#ff6b6b;font-weight:700">❌ Offline</div>'
                    f'<div style="font-size:0.78rem;color:rgba(255,100,100,0.8);margin-top:4px">'
                    f'{db_status["msg"]}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.markdown('<div style="margin-top:12px"></div>', unsafe_allow_html=True)
                with st.expander("View DB Details", expanded=False):
                    st.write("Import OK:", details["import_ok"])
                    st.write("Connected:", details["connected"])
                    st.write("Init OK:", details["init_ok"])
                    st.write("Mode:", details["mode"])
                    st.write("Database:", details["db_name"])
                    st.write("Collections:", details["collections"])
                    st.write("Error:", details["error"])

        st.markdown('<hr style="margin:20px 0">', unsafe_allow_html=True)

        st.markdown(
            """
        <div style="text-align:center;margin:0 0 4px">
            <div style="font-size:1.15rem;font-weight:700;color:white">Generate new survey link</div>
            <div style="font-size:0.74rem;color:rgba(255,255,255,0.5);margin-top:6px">
                Note: editing questions does not affect already-generated links
            </div>
        </div>""",
            unsafe_allow_html=True,
        )

        with st.form("generate_link_form", clear_on_submit=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                sem_in = st.text_input(
                    "_",
                    placeholder="Enter the year and semester (e.g., 2025 Semester 1)",
                    label_visibility="collapsed",
                    key="sem_input_form",
                )
            with c2:
                st.markdown('<div class="arrow-btn">', unsafe_allow_html=True)
                gen_submit = st.form_submit_button("→", use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

        if gen_submit:
            if sem_in and sem_in.strip():
                with st.spinner("Generating link..."):
                    created = create_semester_link(sem_in.strip())
                st.session_state.gen_token = created["token"]
                st.session_state.admin_notice = f"Link generated for {created['label']}"
                st.rerun()
            else:
                st.warning("Enter a semester label first.")

        if st.session_state.admin_notice:
            st.success(st.session_state.admin_notice)

        if st.session_state.gen_token:
            current = get_link_by_token(st.session_state.gen_token)
            lbl = current["label"] if current else "?"
            tok = st.session_state.gen_token
            st.markdown(
                f"""
            <div style="background:rgba(0,0,0,0.3);border-radius:10px;padding:14px 18px;
                        margin-top:12px;border:none">
                <div style="font-size:0.76rem;color:{ACC};font-weight:600;margin-bottom:8px">
                    ✓ Link generated for <strong>{lbl}</strong>
                </div>
                <div style="font-size:0.8rem;color:rgba(255,255,255,0.7)">Share this URL with students:</div>
            </div>""",
                unsafe_allow_html=True,
            )
            st.code(f"https://CourseVoice.streamlit.app/?token={tok}")

    st.markdown('<hr style="margin:32px 0 20px">', unsafe_allow_html=True)
    recent = get_recent_links_with_counts(limit=6)

    if recent:
        st.markdown(
            '<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px">Recent survey links</div>',
            unsafe_allow_html=True,
        )
        for i in range(0, len(recent), 2):
            cols = st.columns(2)
            for j, row in enumerate(recent[i:i + 2]):
                with cols[j]:
                    rc = row.get("response_count", 0)
                    st.markdown(
                        f"""
                    <div style="background:rgba(255,255,255,0.12);border-radius:12px;
                                padding:16px 20px;margin-bottom:10px;
                                border:1px solid rgba(255,255,255,0.18)">
                        <div style="font-weight:700;font-size:1rem;color:white">{row['label']}</div>
                        <div style="font-size:0.78rem;color:rgba(255,255,255,0.55);margin-top:6px">
                            {rc} response(s) &nbsp;·&nbsp; token:
                            <code style="font-size:0.75rem">{row['token']}</code>
                        </div>
                    </div>""",
                        unsafe_allow_html=True,
                    )

# ============================================================================
# SURVEY RESULTS INDEX
# ============================================================================


def page_admin_results():
    render_admin_header()

    st.markdown(
        """
    <div style="text-align:center;font-size:2.6rem;font-weight:800;color:white;
                letter-spacing:-0.5px;margin:0 0 28px">SURVEY RESULTS</div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK", key="back_res"):
        go_admin("home")
    st.markdown("</div><br>", unsafe_allow_html=True)

    sc1, _, sc2 = st.columns([2, 1, 2])
    with sc1:
        st.markdown(
            '<div style="font-size:0.82rem;font-weight:700;color:white;margin-bottom:8px">Sort by</div>',
            unsafe_allow_html=True,
        )
        sort_v = st.radio(
            "_sb",
            ["Year and Semester", "Subjects"],
            index=0 if st.session_state.sort_by == "semester" else 1,
            key="sort_radio",
            label_visibility="hidden",
        )
        st.session_state.sort_by = "semester" if "Semester" in sort_v else "subject"

    with sc2:
        st.markdown(
            '<div style="font-size:0.82rem;font-weight:700;color:white;margin-bottom:8px">Order</div>',
            unsafe_allow_html=True,
        )
        ord_v = st.radio(
            "_ob",
            ["Ascending", "Descending"],
            index=0 if st.session_state.sort_order == "asc" else 1,
            key="order_radio",
            label_visibility="hidden",
        )
        st.session_state.sort_order = "asc" if ord_v == "Ascending" else "desc"

    st.markdown("<br>", unsafe_allow_html=True)

    if st.session_state.sort_by == "semester":
        rows = get_results_index_semester(st.session_state.sort_order)
        if not rows:
            st.info("No survey links yet. Generate one from Admin home.")
            return
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for j, row in enumerate(rows[i:i + 2]):
                with cols[j]:
                    st.markdown('<div class="pill-btn">', unsafe_allow_html=True)
                    cnt = row.get("response_count", 0)
                    lbl = f"{row['label'].upper()}  ({cnt} RESPONSES)"
                    if st.button(lbl, key=f"s_{row['id']}", use_container_width=True):
                        go_admin("detail_semester", drill_link_id=row["id"])
                    st.markdown("</div>", unsafe_allow_html=True)
    else:
        rows = get_results_index_subject(st.session_state.sort_order)
        if not rows:
            st.info("No responses with subject data yet.")
            return
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for j, row in enumerate(rows[i:i + 2]):
                with cols[j]:
                    st.markdown('<div class="pill-btn">', unsafe_allow_html=True)
                    lbl = f"{row['subject_name']}  ({row['cnt']})"
                    if st.button(lbl, key=f"subj_{row['subject_name']}", use_container_width=True):
                        go_admin("detail_subject", drill_subject=row["subject_name"])
                    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# DETAIL: SEMESTER
# ============================================================================


def page_admin_detail_semester():
    render_admin_header()

    link_id = st.session_state.drill_link_id
    link, questions, responses = get_semester_detail_bundle(link_id)

    if not link:
        st.error("Semester not found.")
        return

    st.markdown(
        f"""
    <div style="text-align:center;font-size:2rem;font-weight:800;color:white;margin:0 0 24px">
        {link['label']}
    </div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK TO RESULTS", key="back_det_sem"):
        go_admin("results")
    st.markdown("</div><br>", unsafe_allow_html=True)

    rating_qs = [q for q in questions if q["question_type"] == "rating"]
    all_r = []
    for r in responses:
        ans = parse_answers(r)
        for rq in rating_qs:
            v = safe_int(ans.get(str(rq["id"])))
            if v is not None:
                all_r.append(v)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Responses", len(responses))
    c2.metric("Avg Rating", f"{sum(all_r)/len(all_r):.1f}/5" if all_r else "N/A")
    unique_s = len(set(r["subject_name"] for r in responses if r.get("subject_name")))
    c3.metric("Subjects", unique_s)

    if not responses:
        st.info("No responses yet.")
        return

    summary_payload = []
    for r in responses:
        summary_payload.append(
            {
                "id": r.get("id"),
                "subject_name": r.get("subject_name"),
                "submitted_at": r.get("submitted_at"),
                "answers": parse_answers(r),
            }
        )

    summary_questions = [
    {
        "id": q.get("id"),
        "question_text": q.get("question_text"),
        "question_type": q.get("question_type"),
        "order_num": q.get("order_num"),
    }
        for q in questions
    ]

    with st.spinner("Summarizing this survey..."):
        survey_summary = summarize_survey_responses_with_gemini(
            link["label"],
            json.dumps(summary_questions, ensure_ascii=False),
            json.dumps(summary_payload, ensure_ascii=False),
        )

    st.markdown(
        f"""
        <div style="background:rgba(255,255,255,0.10);border-radius:12px;
                    padding:16px 18px;margin:18px 0 20px;
                    border:1px solid rgba(255,255,255,0.18)">
            <div style="font-size:0.82rem;font-weight:700;color:{ACC};margin-bottom:8px">
                Gemini Summary
            </div>
            <div style="font-size:0.85rem;color:white;line-height:1.6;white-space:pre-wrap">{survey_summary}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-weight:700;color:white;font-size:0.95rem;margin-bottom:12px">Responses by subject</div>',
        unsafe_allow_html=True,
    )
    sc = {}
    for r in responses:
        s = r.get("subject_name") or "Not specified"
        sc[s] = sc.get(s, 0) + 1
    if sc:
        df_sc = pd.DataFrame(sc.items(), columns=["Subject", "Count"]).sort_values("Count", ascending=False)
        st.bar_chart(df_sc.set_index("Subject"))

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-weight:700;color:white;font-size:0.95rem;margin-bottom:12px">{len(responses)} Individual Responses</div>',
        unsafe_allow_html=True,
    )

    for i, r in enumerate(responses):
        ans = parse_answers(r)
        subj = r.get("subject_name") or "Unknown"
        date = r["submitted_at"][:10] if r.get("submitted_at") else "—"
        with st.expander(f"Response #{i+1} — {subj} — {date}"):
            for q in questions:
                val = ans.get(str(q["id"]), "—")
                stars = "⭐" * int(val) if q["question_type"] == "rating" and str(val).isdigit() else ""
                st.markdown(
                    f"""
                <div style="margin-bottom:14px">
                    <div style="font-size:0.74rem;font-weight:600;color:rgba(255,255,255,0.45);margin-bottom:3px">
                        {q['question_text']}
                    </div>
                    <div style="font-size:0.92rem;color:white">{val} {stars}</div>
                </div>""",
                    unsafe_allow_html=True,
                )

    st.markdown('<hr style="margin:20px 0">', unsafe_allow_html=True)
    rows_exp = []
    for r in responses:
        rd = {
            "Semester": link["label"],
            "Subject": r.get("subject_name"),
            "Date": r.get("submitted_at"),
            "Response ID": r.get("id"),
            "Response Mongo OID": r.get("mongo_oid"),
        }
        ans = parse_answers(r)
        for q in questions:
            rd[q["question_text"]] = ans.get(str(q["id"]), "")
        rows_exp.append(rd)
    if rows_exp:
        fn = f"responses_{link['label'].replace(' ', '_')}.csv"
        st.download_button(
            "⬇ Export CSV",
            pd.DataFrame(rows_exp).to_csv(index=False),
            fn,
            "text/csv",
        )

# ============================================================================
# DETAIL: SUBJECT
# ============================================================================


def page_admin_detail_subject():
    render_admin_header()

    subj = st.session_state.drill_subject
    questions, link_map, responses = get_subject_detail_bundle(subj)

    st.markdown(
        f"""
    <div style="text-align:center;font-size:2rem;font-weight:800;color:white;margin:0 0 24px">
        {subj}
    </div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK TO RESULTS", key="back_det_subj"):
        go_admin("results")
    st.markdown("</div><br>", unsafe_allow_html=True)

    all_r = []
    for r in responses:
        ans = parse_answers(r)
        for q in questions:
            if q["question_type"] == "rating":
                v = safe_int(ans.get(str(q["id"])))
                if v is not None:
                    all_r.append(v)

    c1, c2 = st.columns(2)
    c1.metric("Total Responses", len(responses))
    c2.metric("Avg Rating", f"{sum(all_r)/len(all_r):.1f}/5" if all_r else "N/A")

    if not responses:
        st.info("No responses for this subject.")
        return

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    for i, r in enumerate(responses):
        ans = parse_answers(r)
        sem_label = link_map.get(r["link_id"], {}).get("label", "Unknown")
        safe_date = r["submitted_at"][:10] if r.get("submitted_at") else "—"
        with st.expander(f"Response #{i+1} — {sem_label} — {safe_date}"):
            for q in questions:
                if q["question_type"] == "dropdown":
                    continue
                val = ans.get(str(q["id"]), "—")
                stars = "⭐" * int(val) if q["question_type"] == "rating" and str(val).isdigit() else ""
                st.markdown(
                    f"""
                <div style="margin-bottom:14px">
                    <div style="font-size:0.74rem;font-weight:600;color:rgba(255,255,255,0.45);margin-bottom:3px">
                        {q['question_text']}
                    </div>
                    <div style="font-size:0.92rem;color:white">{val} {stars}</div>
                </div>""",
                    unsafe_allow_html=True,
                )

# ============================================================================
# EDIT SURVEY
# ============================================================================


def page_admin_edit():
    render_admin_header()

    st.markdown(
        """
    <div style="text-align:center;font-size:2.4rem;font-weight:800;color:white;
                letter-spacing:-0.5px;margin:0 0 24px">EDIT SURVEY</div>""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("← BACK", key="back_edit"):
        go_admin("home")
    st.markdown("</div><br>", unsafe_allow_html=True)

    questions = get_active_questions()
    subjects = get_active_subjects()

    TYPE_OPTS = ["dropdown", "text", "rating", "yes_no"]
    TYPE_LABELS = ["Dropdown ▼", "Text", "Rating (1-5)", "Yes / No"]
    TYPE_MAP = dict(zip(TYPE_OPTS, TYPE_LABELS))
    TYPE_REV = dict(zip(TYPE_LABELS, TYPE_OPTS))

    h0, h1, h2, h3, h4 = st.columns([0.5, 4, 2, 1.5, 1.2])
    for txt, col in [("No.", h0), ("Question", h1), ("Type", h2), ("AI Check", h3), ("Remove", h4)]:
        col.markdown(
            f'<div style="font-size:0.78rem;font-weight:700;color:rgba(255,255,255,0.55);'
            f'padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.2)">{txt}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    for i, q in enumerate(questions):
        c0, c1, c2, c3, c4 = st.columns([0.5, 4, 2, 1.5, 1.2])
        with c0:
            st.markdown(
                f'<div style="padding:14px 0;font-size:0.9rem;color:rgba(255,255,255,0.7)">{i+1}</div>',
                unsafe_allow_html=True,
            )
        with c1:
            st.text_input(
                "_",
                value=q["question_text"],
                label_visibility="collapsed",
                key=f"qt_{q['id']}",
            )
        with c2:
            cur_lbl = TYPE_MAP.get(q["question_type"], "Text")
            idx = TYPE_LABELS.index(cur_lbl) if cur_lbl in TYPE_LABELS else 1
            st.selectbox(
                "_",
                TYPE_LABELS,
                index=idx,
                label_visibility="collapsed",
                key=f"qtp_{q['id']}",
            )
        with c3:
            current_type = TYPE_REV.get(st.session_state.get(f"qtp_{q['id']}", TYPE_MAP.get(q["question_type"])), q["question_type"])
            if current_type == "text":
                st.toggle(
                    "🤖",
                    value=bool(q.get("ai_moderated", 0)),
                    key=f"qai_{q['id']}",
                    help="Enable AI moderation for this answer",
                )
            else:
                st.markdown(
                    '<div style="padding:14px 0;font-size:0.8rem;color:rgba(255,255,255,0.25)">—</div>',
                    unsafe_allow_html=True,
                )
        with c4:
            st.markdown('<div class="rem-btn">', unsafe_allow_html=True)
            if st.button("−", key=f"rm_{q['id']}"):
                soft_remove_question(q["id"])
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _, sc, _ = st.columns([1, 2, 1])
    with sc:
        st.markdown('<div class="save-btn">', unsafe_allow_html=True)
        if st.button("💾 SAVE ALL CHANGES", use_container_width=True, key="save_all"):
            payload = []
            for q in questions:
                nt = st.session_state.get(f"qt_{q['id']}", q["question_text"]).strip()
                nl = st.session_state.get(f"qtp_{q['id']}", TYPE_MAP.get(q["question_type"]))
                qtype = TYPE_REV.get(nl, q["question_type"])
                payload.append(
                    {
                        "id": q["id"],
                        "question_text": nt,
                        "question_type": qtype,
                        "ai_moderated": 1 if (qtype == "text" and st.session_state.get(f"qai_{q['id']}", False)) else 0,
                    }
                )
            save_questions_bulk(payload)
            st.success("Saved!")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<hr style="margin:24px 0">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.82rem;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:10px">Add new question</div>',
        unsafe_allow_html=True,
    )

    na0, na1, na2, na3, na4 = st.columns([0.5, 4, 2, 1.5, 1.2])
    with na0:
        st.markdown(
            f'<div style="padding:14px 0;font-size:0.9rem;color:rgba(255,255,255,0.35)">{len(questions)+1}</div>',
            unsafe_allow_html=True,
        )
    with na1:
        nq_text = st.text_input(
            "_",
            placeholder="New question text…",
            label_visibility="collapsed",
            key="nq_text",
        )
    with na2:
        nq_type_lbl = st.selectbox(
            "_",
            TYPE_LABELS,
            label_visibility="collapsed",
            key="nq_type",
        )
    with na3:
        if nq_type_lbl == "Text":
            nq_ai = st.toggle(
                "🤖",
                value=False,
                key="nq_ai",
                help="Enable AI moderation for this answer",
            )
        else:
            nq_ai = False
            st.markdown(
                '<div style="padding:14px 0;font-size:0.8rem;color:rgba(255,255,255,0.25)">—</div>',
                unsafe_allow_html=True,
            )
    with na4:
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("＋", key="add_q"):
            if nq_text.strip():
                qtype = TYPE_REV.get(nq_type_lbl, "text")
                add_question(nq_text.strip(), qtype, 1 if (qtype == "text" and nq_ai) else 0)
                st.rerun()
            else:
                st.warning("Enter question text.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<hr style="margin:28px 0">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:1rem;font-weight:700;color:white;margin-bottom:14px">Subjects (for Dropdown question)</div>',
        unsafe_allow_html=True,
    )

    for subj in subjects:
        s1, s2 = st.columns([7, 1.5])
        with s1:
            st.markdown(
                f'<div style="padding:10px 0;font-size:0.9rem;color:rgba(255,255,255,0.85)">• {subj["name"]}</div>',
                unsafe_allow_html=True,
            )
        with s2:
            st.markdown('<div class="rem-btn">', unsafe_allow_html=True)
            if st.button("−", key=f"rs_{subj['id']}"):
                soft_remove_subject(subj["id"])
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    a1, a2 = st.columns([7, 1.5])
    with a1:
        ns = st.text_input(
            "_",
            placeholder="Add new subject…",
            label_visibility="collapsed",
            key="new_subj",
        )
    with a2:
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("＋", key="add_s"):
            if ns.strip():
                add_or_reactivate_subject(ns.strip())
                st.rerun()
            else:
                st.warning("Enter a subject name.")
        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# ADMIN DISPATCHER
# ============================================================================


def page_admin():
    av = st.session_state.admin_view
    if av == "home":
        page_admin_home()
    elif av == "results":
        page_admin_results()
    elif av == "detail_semester":
        page_admin_detail_semester()
    elif av == "detail_subject":
        page_admin_detail_subject()
    elif av == "edit":
        page_admin_edit()
    else:
        st.session_state.admin_view = "home"
        page_admin_home()

# ============================================================================
# ROUTER
# ============================================================================

if TOKEN:
    page_student(TOKEN)
elif ADMIN_PARAM is not None or st.session_state.admin_logged_in:
    if st.session_state.admin_logged_in:
        page_admin()
    else:
        page_login()
else:
    page_landing()
