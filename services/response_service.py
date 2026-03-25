from db_collections import responses_col, counters_col
from pymongo import ReturnDocument
from datetime import datetime


def get_next_id(counter_name):
    doc = counters_col().find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        return_document=ReturnDocument.BEFORE
    )
    return doc["seq"]


def create_response(link_id, subject_name, answers_json):
    doc = {
        "id": get_next_id("responses"),
        "link_id": link_id,
        "subject_name": subject_name,
        "answers_json": answers_json,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    responses_col().insert_one(doc)
    return doc


def get_responses_by_link(link_id):
    return list(responses_col().find({"link_id": link_id}, {"_id": 0}).sort("submitted_at", -1))


def get_responses_by_subject(subject_name):
    return list(responses_col().find({"subject_name": subject_name}, {"_id": 0}).sort("submitted_at", -1))


def get_all_responses():
    return list(responses_col().find({}, {"_id": 0}))