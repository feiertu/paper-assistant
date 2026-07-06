"""Test embedding API compatibility."""
import os, json
import requests

def test_minimax():
    key = os.getenv('EMBEDDING_API_KEY', '')
    url = os.getenv('EMBEDDING_BASE_URL', '') + '/embeddings'
    print(f"Testing: {url}")
    print(f"Key set: {bool(key)}")

    # Test with 'texts' (MiniMax format)
    resp = requests.post(url,
        json={'model': 'text-embedding-3-large', 'texts': ['hello world']},
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        timeout=10)
    data = resp.json()
    print(f"Status: {resp.status_code}")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:500])

if __name__ == "__main__":
    test_minimax()
