from db_collections import admins_col
from security import hpw

def find_admin(username, password):
    return admins_col().find_one({
        "username": username,
        "password_hash": hpw(password)
    })