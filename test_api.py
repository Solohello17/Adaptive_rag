import json
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_path(question, name):
    print(f"\n=== {name} ===")
    response = client.post("/query", json={"question": question})
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    test_path("Hello there! How are you?", "General Knowledge Path")
    test_path("What are the main findings in the Q3 financial report?", "Documents Path")
    test_path("What is the current price of Bitcoin?", "Web Search Path")
