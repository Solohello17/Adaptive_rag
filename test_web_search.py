from dotenv import load_dotenv
load_dotenv()

from app.graph import rag_app

if __name__ == "__main__":
    print("\n--- TEST: Web Search ---")
    response = rag_app.invoke({"question": "What is the current price of Bitcoin?"})
    print("\nFinal Answer:")
    print(response["generation"])
