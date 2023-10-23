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
                    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


    def get_all_for_user(username: str):
        sessions = {}
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, created_time, username FROM user_sessions WHERE username=?",
                (username,)
            )
            rows = cursor.fetchall()
        
            for row in rows:
                id, created_time, row_username = row
                sessions[id] = {'id': id, 'username': row_username, 'created_time': created_time}

        return sessions

    def get_all(from_seconds: int = 3600*24):
        sessions = {}
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, created_time, username FROM user_sessions WHERE created_time > DATETIME(CURRENT_TIMESTAMP, '-' || ? || ' seconds')",
                (from_seconds, )
            )
            rows = cursor.fetchall()
        
            for row in rows:
                id, created_time, row_username = row
                sessions[id] = {'id': id, 'username': row_username, 'created_time': created_time}

        return sessions
