import os
from openai import AzureOpenAI
from dotenv import load_dotenv

# Load credentials
load_dotenv()

print("🔍 Connecting to Azure OpenAI...")

try:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_DEPLOYMENT_NAME")

    client = AzureOpenAI(
        api_key=api_key,  
        api_version="2024-02-15-preview",
        azure_endpoint=endpoint
    )

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello Azure! Are you ready?"}
        ]
    )

    print("\n🎉 SUCCESS! Azure Responded:")
    print(response.choices[0].message.content)

except Exception as e:
    print(f"\n❌ Error: {e}")
