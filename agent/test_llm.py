import os
from google import genai

import kit
os.environ.setdefault("GOOGLE_API_KEY", kit.ENV["GOOGLE_API_KEY"])


# charge GOOGLE_API_KEY depuis .env comme le fait le kit (ou fais export avant)
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
r = client.models.generate_content(model="gemini-flash-latest", contents="Réponds juste : ok")
print(r.text)