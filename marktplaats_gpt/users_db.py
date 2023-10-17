import sqlite3


DB_FILE = 'users.db'

class UserDB:
    def init_db():
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    modified_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    setting_key TEXT,
                    setting_value TEXT,
                    UNIQUE(username, setting_key)
                )
            ''')
            conn.commit()


    def set(username: str, key: str, value: str):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_settings (username, setting_key, setting_value) VALUES (?, ?, ?)",
                (username, key, value)
            )
            conn.commit()


    def delete(username: str, key: str):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_settings WHERE username=? and setting_key=?",
                (username, key)
            )
            conn.commit()


    def get(username: str, key: str) -> str:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT setting_value FROM user_settings WHERE username=? and setting_key=?",
                (username, key)
            )
            selection = cursor.fetchone()
            if selection:
                value, = selection
                return value
            else:
                return None

    def get_all(username: str):
        settings = {}
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT setting_key, setting_value, modified_time FROM user_settings WHERE username=?",
                (username,)
            )
            rows = cursor.fetchall()
        
            for row in rows:
                setting_key, setting_value, modified_time = row
                settings[setting_key] = {'value': setting_value, 'modified_time': modified_time}

        return settings