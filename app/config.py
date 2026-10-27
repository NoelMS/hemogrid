import os

PG_DSN = os.environ.get("HEMO_PG", "host=127.0.0.1 port=54329 dbname=hemogrid user=postgres options=-csearch_path=hemo")
MONGO_URI = os.environ.get("HEMO_MONGO", "mongodb://127.0.0.1:27018")
