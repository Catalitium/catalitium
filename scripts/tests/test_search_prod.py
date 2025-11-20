from urllib import request, parse
import json

BASE = "https://catalitium-jobs.fly.dev"

def fetch_api(title, country="", per_page=5):
    params = {"title": title, "per_page": str(per_page)}
    if country:
        params["country"] = country
    url = f"{BASE}/api/jobs?" + parse.urlencode(params)
    with request.urlopen(url, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body)

if __name__ == "__main__":
    status, payload = fetch_api("engineer")
    print("status", status)
    print("count", payload.get("meta", {}).get("total"))
    if payload.get("items"):
        print("sample", payload["items"][0])
    else:
        print("no items returned")
