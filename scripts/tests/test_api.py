from urllib import request, parse, error
import pytest

params = parse.urlencode({"title": "engineer", "per_page": "5"})
url = f"https://catalitium-jobs.fly.dev/api/jobs?{params}"

try:
    with request.urlopen(url, timeout=15) as resp:
        print(resp.status)
        body = resp.read().decode('utf-8')
        print(body[:2000])
except (error.URLError, OSError) as exc:
    pytest.skip(f"External API unavailable: {exc}", allow_module_level=True)
