from db.mongo import get_database


def admins_col():
    return get_database()["admins"]


def subjects_col():
    return get_database()["subjects"]


def questions_col():
    return get_database()["questions"]


def semester_links_col():
    return get_database()["semester_links"]


def responses_col():
    return get_database()["responses"]


def counters_col():
    return get_database()["counters"]