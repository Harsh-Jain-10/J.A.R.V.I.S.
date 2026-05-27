import sqlite3
conn = sqlite3.connect('jarvis_memory.db')
cur = conn.cursor()
tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', tables)
for t in tables:
    name = t[0]
    cols = cur.execute(f'PRAGMA table_info({name})').fetchall()
    print(f'{name} columns:', [c[1] for c in cols])
    rows = cur.execute(f'SELECT * FROM {name} LIMIT 10').fetchall()
    for r in rows:
        print(' ', r)
conn.close()
