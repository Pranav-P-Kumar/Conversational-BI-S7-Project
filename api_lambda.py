
import requests
import json
import boto3
import pandas as pd
import psycopg2
from typing import Union
import sqlglot
import time 
from dotenv import load_dotenv
import os

load_dotenv() 
API_BASE = os.getenv("API_BASE")
 
class ValidationError(Exception): 
    pass

class Chatbot():
    def __init__(self,secrets, config=None):

        if config is None:
            config = {} 
        self.config = config
        self.static_documentation = ""
        self.run_sql_is_set = False
        self.dialect = self.config.get("dialect", "SQL")
        self.language = self.config.get("language", None)
        self.max_tokens = self.config.get("max_tokens", 14000)

    def connect_to_postgres(
        self,
        host: str = None,
        dbname: str = None,
        user: str = None,
        password: str = None,
        port: int = None,

        **kwargs
    ):
        conn = None 
        try:
            conn = psycopg2.connect(
                host=host,
                dbname=dbname,
                user=user,
                password=password,
                port=port,
                **kwargs
            )
        except psycopg2.Error as e:
            raise ValidationError(e)
        def connect_to_db():
            return psycopg2.connect(host=host, dbname=dbname,
                        user=user, password=password, port=port, **kwargs)
        try:
            conn = connect_to_db()   
            cs = conn.cursor()                            
        except Exception as e:
                        conn.rollback()
                        raise e

        def run_sql_postgres(sql) : 
            conn = None
            limit=20
            if "limit" not in sql.lower():
                sql = f"{sql.rstrip(';')} LIMIT {limit}"
            try:
                conn = connect_to_db()
                cs = conn.cursor() 
                cs.execute(sql)
                results = cs.fetchmany(limit)

                df = pd.DataFrame(results, columns=[desc[0] for desc in cs.description])
                return df
            except psycopg2.InterfaceError as e:
                if conn:
                    conn.close()  
                conn = connect_to_db()
                cs = conn.cursor()
                cs.execute(sql)
                results = cs.fetchall()
                df = pd.DataFrame(results, columns=[desc[0] for desc in cs.description])
                return df

            except psycopg2.Error as e:
                if conn:
                    conn.rollback()
                    raise ValidationError(e)

            except Exception as e:
                        conn.rollback()
                        raise e

        self.dialect = "PostgreSQL"
        self.run_sql_is_set = True
        self.run_sql = run_sql_postgres   
 
    def get_result_sql(self,sql):
        try:
            fixed_sql = sqlglot.parse_one(sql).sql(dialect="postgres")
            if "#" in fixed_sql:
                fixed_sql = fixed_sql.replace("#", "^")
            df = self.run_sql(fixed_sql)
            return df

        except Exception as e:
            print("Couldn't run sql: ", e)
            return None 

def get_aws_secrets(secret_name: str, region_name: str):
    client = boto3.client("secretsmanager",
    region_name=region_name,          
    aws_access_key_id=os.getenv("aws_access_key_id"),
    aws_secret_access_key=os.getenv("aws_secret_access_key")
 )
    response = client.get_secret_value(SecretId=secret_name)
    secret_string = response["SecretString"]
    return json.loads(secret_string)

def warmup_api(max_retries=5, delay=5):  

    url = f"{API_BASE}/get-code"
    payload = {"question": "warmup check"}   

    for attempt in range(1, max_retries + 1):
        print("Warming up attempt ",attempt)
        try: 
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code == 200: 
                return True
            else:
                print(f"Response: {resp.status_code}, retrying in {delay}s...")
        except Exception as e:
            print(f"Warm-up failed: {e}, retrying in {delay}s...")

        time.sleep(delay) 
    print("API did not become ready after retries.")
    return False
secrets = get_aws_secrets("convbi_intern_db", region_name="ap-south-1")
vn = Chatbot(secrets)
vn.connect_to_postgres(
    host=secrets["rds"]["host"],
    dbname=secrets["rds"]["dbname"],
    user=secrets["rds"]["user"],
    password=secrets["rds"]["password"],
    port=secrets["rds"]["port"]
) 
def getRes(query): 
    if not warmup_api(): 
        return -1 
    question_entered = query  
    url = f"{API_BASE}/get-code"
    payload = {"question": question_entered} 
    resp = requests.post(url, json=payload, timeout=120) 
    if resp.status_code == 200:
        try:
            data = resp.json()
            print("Response JSON:\n")
            print(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            print("Raw response (not JSON):")
            print(resp.text)
            return -1
  
        sql_query = data.get("sql_query")
        if sql_query:
            query_result_df = vn.get_result_sql(sql_query)
            if isinstance(query_result_df, pd.DataFrame):
                return query_result_df
    return -1 



print(getRes("Whats the sales of year 2023"))