from db_collections import questions_col, counters_col
from pymongo import ReturnDocument


def get_next_id(counter_name):
    doc = counters_col().find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        return_document=ReturnDocument.BEFORE
    )
    return doc["seq"]


def get_active_questions():
    return list(questions_col().find({"active": 1}, {"_id": 0}).sort("order_num", 1))


def add_question(question_text, question_type, order_num, ai_moderated=0):
    questions_col().insert_one({
        "id": get_next_id("questions"),
        "question_text": question_text,
        "question_type": question_type,
        "order_num": order_num,
        "active": 1,
        "ai_moderated": ai_moderated
    })


def update_question(question_id, updates):
    questions_col().update_one({"id": question_id}, {"$set": updates})


def deactivate_question(question_id):
    questions_col().update_one({"id": question_id}, {"$set": {"active": 0}})