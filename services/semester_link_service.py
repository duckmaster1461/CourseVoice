from db.db_collections import semester_links_col, counters_col
from pymongo import ReturnDocument
from datetime import datetime
import uuid

def get_next_id(counter_name):
    doc = counters_col().find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        return_document=ReturnDocument.BEFORE
    )
    return doc["seq"]

def create_semester_link(label):
    token = uuid.uuid4().hex[:8].upper()
    doc = {
        "id": get_next_id("semester_links"),
        "label": label,
        "token": token,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    semester_links_col().insert_one(doc)
    return doc

def get_link_by_token(token):
    return semester_links_col().find_one({"token": token}, {"_id": 0})

def get_all_links():
    return list(semester_links_col().find({}, {"_id": 0}))