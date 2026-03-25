from db_collections import subjects_col, counters_col
from pymongo import ReturnDocument

def get_next_id(counter_name):
    doc = counters_col().find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        return_document=ReturnDocument.BEFORE
    )
    return doc["seq"]

def get_active_subjects():
    return list(subjects_col().find({"active": 1}, {"_id": 0}).sort("name", 1))

def add_subject(name):
    existing = subjects_col().find_one({"name": name})
    if existing:
        subjects_col().update_one({"name": name}, {"$set": {"active": 1}})
        return
    subjects_col().insert_one({
        "id": get_next_id("subjects"),
        "name": name,
        "active": 1
    })

def deactivate_subject(subject_id):
    subjects_col().update_one({"id": subject_id}, {"$set": {"active": 0}})