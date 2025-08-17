import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore

def init_db_from_secrets():
    sa_json = st.secrets.get("firebase_service_account")
    if not sa_json:
        raise RuntimeError("Missing firebase_service_account in Streamlit secrets")
    sa = json.loads(sa_json)

    # fix escaped newlines if the key was pasted with literal backslash-n
    if "private_key" in sa and isinstance(sa["private_key"], str):
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(sa)
        app = firebase_admin.initialize_app(cred)

    db = firestore.client(app=app)
    return db

# initialize
try:
    db = init_db_from_secrets()
    st.success("Firebase initialized")
except Exception as e:
    st.error("Firebase init failed: " + str(e))
    st.stop()
