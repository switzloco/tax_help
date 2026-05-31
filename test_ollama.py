import json
import urllib.request

def test_ollama():
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": "gemma4:26b",
        "messages": [
            {"role": "system", "content": "You are a CPA. Write a very brief email saying hi."},
            {"role": "user", "content": "Say hello!"}
        ],
        "stream": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            print(f"Response: '{res_data['message']['content']}'")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ollama()
