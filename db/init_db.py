import hashlib
from db.db_collections import admins_col, subjects_col, questions_col, counters_col


def hpw(p):
    return hashlib.sha256(p.encode()).hexdigest()


def init_db():
    if admins_col().count_documents({}) == 0:
        admins_col().insert_one({
            "id": 1,
            "username": "admin",
            "password_hash": hpw("admin123")
        })

    if subjects_col().count_documents({}) == 0:
        default_subjects = [
            "AP Physics 1",
            "IB English HL",
            "IB English SL",
            "IM 1",
            "IM 2",
            "IM 3",
            "Physics",
            "Symphonic Band"
        ]
        subjects_col().insert_many([
            {"id": i + 1, "name": s, "active": 1}
            for i, s in enumerate(default_subjects)
        ])

    if questions_col().count_documents({}) == 0:
        questions_col().insert_many([
            {
                "id": 1,
                "question_text": "Which subject is this about?",
                "question_type": "dropdown",
                "order_num": 1,
                "active": 1,
                "ai_moderated": 0
            },
            {
                "id": 2,
                "question_text": "How has this course helped you?",
                "question_type": "text",
                "order_num": 2,
                "active": 1,
                "ai_moderated": 1
            },
            {
                "id": 3,
                "question_text": "How difficult was the course?",
                "question_type": "rating",
                "order_num": 3,
                "active": 1,
                "ai_moderated": 0
            },
            {
                "id": 4,
                "question_text": "Do you think the course should be offered again?",
                "question_type": "yes_no",
                "order_num": 4,
                "active": 1,
                "ai_moderated": 0
            },
        ])

    for name, start in {
        "subjects": 9,
        "questions": 5,
        "semester_links": 1,
        "responses": 1
    }.items():
        if counters_col().count_documents({"_id": name}) == 0:
            counters_col().insert_one({"_id": name, "seq": start})