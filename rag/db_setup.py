import os
import psycopg2

def init_db():
    connection = None
    try:
        # Connect to the Dockerized Postgres instance
        connection = psycopg2.connect(
            user="myuser",
            password="mypassword",
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port="5432",
            database="mydatabase"
        )
        with connection.cursor() as cur:
            with open('db/init.sql', 'r') as f:
                sql_script = f.read()

            cur.execute(sql_script)

            connection.commit()

    except (Exception, psycopg2.Error) as error:
        print("Error while connecting to PostgreSQL", error)

    finally:
        if connection:
            connection.close()
