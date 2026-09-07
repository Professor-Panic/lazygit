import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()  # reads .env and loads ANTHROPIC_API_KEY into the environment

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def call_anthropic(diff_text):
   prompt = f"""
            You are an expert software engineer writing a git commit message.
            Given the diff below, respond with ONLY a JSON object, no other text before or after, in exactly this format:
            {{
               "summary": "a single-line summary under 72 characters", 
               "full": "a fuller multi-line message: summary line, blank line, then bullet points on what changed and why"
            }}

            Diff:
            {diff_text}
            """         

   response = client.messages.create(
      model="claude-sonnet-5",
      max_tokens=500,
      messages=[{"role": "user", "content": prompt}]
   )

   raw_text = response.content[0].text
   return json.loads(raw_text)
            
            
            
