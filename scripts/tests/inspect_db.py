import os, sqlite3, sys

DB_PATH = os.path.join('data','catalitium.db')
if not os.path.exists(DB_PATH):
    print('DB missing:', DB_PATH)
    sys.exit(0)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

def safe_count(table):
    try:
        cur.execute(f'SELECT COUNT(1) FROM {table}')
        return cur.fetchone()[0]
    except Exception as e:
        return f'err:{e}'

def topn(sql, n=10):
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        return [(rows[i][0], rows[i][1]) for i in range(min(n, len(rows)))]
    except Exception as e:
        return [('err', str(e))]

stats = {}
for t in ['jobs', 'subscribers']:
    stats[t] = safe_count(t)

try:
    cur.execute("SELECT COUNT(1) FROM jobs WHERE link IS NULL OR TRIM(link)='' ")
    null_links = cur.fetchone()[0]
except Exception as e:
    null_links = f'err:{e}'

top_titles = topn("SELECT job_title, COUNT(1) c FROM jobs GROUP BY job_title ORDER BY c DESC LIMIT 10")
top_locs = topn("SELECT location, COUNT(1) c FROM jobs GROUP BY location ORDER BY c DESC LIMIT 10")

print('TABLE_COUNTS=', stats)
print('NULL_LINKS=', null_links)
print('TOP_TITLES=', top_titles)
print('TOP_LOCS=', top_locs)

