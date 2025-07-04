import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY","xxx"))

# Repalce with the youtube url you want to analyze
youtube_url = "https://www.youtube.com/watch?v=RDOMKIw1aF4" 

# Prompt to analyze and summarize the Youtube Video
prompt = """Analyze the following YouTube video content. Provide a concise summary covering:

1.  **Main Thesis/Claim:** What is the central point the creator is making?
2.  **Key Topics:** List the main subjects discussed, referencing specific examples or technologies mentioned (e.g., AI models, programming languages, projects).
3.  **Call to Action:** Identify any explicit requests made to the viewer.
4.  **Summary:** Provide a concise summary of the video content.

Use the provided title, chapter timestamps/descriptions, and description text for your analysis."""

# Analyze the video
response = client.models.generate_content(
    model="gemini-2.5-pro-exp-03-25",
    contents=types.Content(
        parts=[
            types.Part(text=prompt),
            types.Part(
                file_data=types.FileData(file_uri=youtube_url)
            )
        ]
    )
)

print(response.text)