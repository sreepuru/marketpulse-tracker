import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

c = psycopg2.connect(
    host=os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    port=int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
    dbname=os.getenv("MARKETPULSE_DB_NAME"),
    user=os.getenv("MARKETPULSE_DB_USER"),
    password=os.getenv("MARKETPULSE_DB_PASSWORD"),
)

cur = c.cursor()

cur.execute("SELECT current_database(), current_schema(), current_user")
print("CONNECTION =", cur.fetchone())

cur.execute("SHOW search_path")
print("SEARCH_PATH =", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM security_master")
print("security_master =", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM marketpulse_historical_identity_evidence")
print("historical_evidence =", cur.fetchone()[0])

c.close()