import hashlib
from db.db_collections import (
    admins_col,
    subjects_col,
    questions_col,
    semester_links_col,
    responses_col,
    counters_col,
)


def hpw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def seed_payload():
    return {
        "admins": [
            {
                "id": 1,
                "username": "admin",
                "password_hash": hpw("admin123"),
            }
        ],
        "subjects": [
            {"id": i + 1, "name": s, "active": 1}
            for i, s in enumerate(
                [
                    "AP Physics 1",
                    "IB English HL",
                    "IB English SL",
                    "IM 1",
                    "IM 2",
                    "IM 3",
                    "Physics",
                    "Symphonic Band",
                ]
            )
        ],
        "questions": [
            {
                "id": 1,
                "question_text": "Which subject is this about?",
                "question_type": "dropdown",
                "order_num": 1,
                "active": 1,
                "ai_moderated": 0,
            },
            {
                "id": 2,
                "question_text": "How has this course helped you?",
                "question_type": "text",
                "order_num": 2,
                "active": 1,
                "ai_moderated": 1,
            },
            {
                "id": 3,
                "question_text": "How difficult was the course?",
                "question_type": "rating",
                "order_num": 3,
                "active": 1,
                "ai_moderated": 0,
            },
            {
                "id": 4,
                "question_text": "Do you think the course should be offered again?",
                "question_type": "yes_no",
                "order_num": 4,
                "active": 1,
                "ai_moderated": 0,
            },
        ],
        "semester_links": [],
        "responses": [],
        "_next_ids": {
            "subjects": 9,
            "questions": 5,
            "semester_links": 1,
            "responses": 1,
        },
    }


def init_db():
    data = seed_payload()

    # Seed main collections only if empty
    if admins_col().count_documents({}) == 0:
        admins_col().insert_many(data["admins"])

    if subjects_col().count_documents({}) == 0:
        subjects_col().insert_many(data["subjects"])

    if questions_col().count_documents({}) == 0:
        questions_col().insert_many(data["questions"])

    # These create the collections explicitly if they do not exist yet.
    # They stay empty until the app writes to them.
    if "semester_links" not in admins_col().database.list_collection_names():
        semester_links_col().insert_many(data["semester_links"]) if data["semester_links"] else semester_links_col().insert_one({"__seed__": True})
        semester_links_col().delete_many({"__seed__": True})

    if "responses" not in admins_col().database.list_collection_names():
        responses_col().insert_many(data["responses"]) if data["responses"] else responses_col().insert_one({"__seed__": True})
        responses_col().delete_many({"__seed__": True})

    # Seed counters
    for name, start in data["_next_ids"].items():
        if counters_col().count_documents({"_id": name}) == 0:
            counters_col().insert_one({"_id": name, "seq": start})

    # Useful indexes
    admins_col().create_index("username", unique=True)
    subjects_col().create_index("id", unique=True)
    questions_col().create_index("id", unique=True)
    semester_links_col().create_index("id", unique=True)
    semester_links_col().create_index("token", unique=True)
    responses_col().create_index("id", unique=True)
    responses_col().create_index("link_id")
    responses_col().create_index("subject_name")