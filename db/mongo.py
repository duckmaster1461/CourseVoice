from pymongo import MongoClient
import streamlit as st

@st.cache_resource
def get_mongo_client():
    return MongoClient(st.secrets["MONGODB_URI"])

def get_database():
    client = get_mongo_client()
    db_name = st.secrets.get("MONGODB_DB", "coursevoice")
    return client[db_name]