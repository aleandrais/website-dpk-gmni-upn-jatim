"""Run after starting server.py: python tests/smoke_test.py"""
import json, urllib.request, urllib.error, http.cookiejar
BASE='http://127.0.0.1:8000'
def get(path):
    with urllib.request.urlopen(BASE+path) as r:return json.loads(r.read())
def main():
    stats=get('/api/stats'); assert all(k in stats for k in ('members','events','articles','albums'))
    structure=get('/api/structure')
    serialized=json.dumps(structure).lower()
    for forbidden in ('nim','email','phone','address','@dpk-gmni'):
        assert forbidden not in serialized, f'Public structure leaked {forbidden}'
    assert 'departments' in structure
    articles=get('/api/articles'); assert 'items' in articles
    events=get('/api/events'); assert 'items' in events
    print('PASS: stats, public structure privacy, public articles, public events')
if __name__=='__main__':main()
