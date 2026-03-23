from db.collections import admins_col
from utils.security import hpw

def find_admin(username, password):
    return admins_col().find_one({
        "username": username,
        "password_hash": hpw(password)
    })