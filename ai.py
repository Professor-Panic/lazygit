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


   #Instead of asking the model for a "summary and a full message" in free-form text 
   # and then trying to guess where one ends and the other begins, JSON gives you a format Python can parse reliably with json.loads()
   raw_text = response.content[0].text  #Claude's API returns a list of content blocks
   return json.loads(raw_text) #turns the JSON string into an actual Python dict, so you can access result["summary"] and result["full"] afterward.
            

def call_ollama(diff_text, model="llama3.2"):
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
    response = request.post(
        "http://localhost:11434/api/generate",
        json={"model":model, "prompt":prompt, "stream": False},
        timeout=30,
    )
    response.raise_for_status()
    raw_text = response.json()["response"]
    return json.loads(raw_text)


"""
Tries Claude first (best quality). Falls back to local Ollama if the
    API call fails for any reason — out of credits, no internet, bad key,
    rate limited, etc. Whoever answers, the shape returned is identical:
    {"summary": ..., "full": ...}.
"""

def suggest_commit_message(diff_text):
    try:
        return call_anthropic(diff_text)
    except Exception as e: #A broad catch -> so that no matter why the primary failed, use the backup.
        print(f"[ai] Anthropic call failed ({e}), falling back to Ollama...")
        return call_ollama(diff_text)
            
