import sqlite3


DB_FILE = 'sessions.db'

class SessionDB:
    def init_db():
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NULL,
                    prompt_tokens INTEGER NULL,
                    completion_tokens INTEGER NULL
                )
            ''')
            conn.commit()


    def create(username: str):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_sessions (username) VALUES (?)",
                (username,)
            )
            conn.commit()

    
    def use(username: str, model: str, prompt_tokens: int, completion_tokens: int):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_sessions (username, model, prompt_tokens, completion_tokens) VALUES (?,?,?,?)",
                (username, model, prompt_tokens, completion_tokens)
            )
            conn.commit()


    def get_all_for_user(username: str):
        sessions = {}
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, created_time, username, model, prompt_tokens, completion_tokens FROM user_sessions WHERE username=?",
                (username,)
            )
            rows = cursor.fetchall()
        
            for row in rows:
                id, created_time, row_username, model, prompt_tokens, completion_tokens = row
                sessions[id] = {
                    'id': id,
                    'username': row_username,
                    'created_time': created_time,
                    'model': model,
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens
                }

        return sessions

    def get_all(from_seconds: int = 3600*24):
        sessions = {}
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, created_time, username, model, prompt_tokens, completion_tokens FROM user_sessions WHERE created_time > DATETIME(CURRENT_TIMESTAMP, '-' || ? || ' seconds')",
                (from_seconds, )
            )
            rows = cursor.fetchall()
        
            for row in rows:
                id, created_time, row_username, model, prompt_tokens, completion_tokens = row
                sessions[id] = {
                    'id': id,
                    'username': row_username,
                    'created_time': created_time,
                    'model': model,
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens
                }

        return sessions
