import os
import json
import asyncio
import base64
from openai import AsyncOpenAI

class JudgeService:
    def __init__(self):
        # Grabs your GROQ_API_KEY from .env and routes to Groq servers
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("[JUDGE ERROR]: GROQ_API_KEY is missing from your .env file!")

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )
        print("[JUDGE AGENT]: Initialized online Groq AI Judge.")

    async def transcribe_audio(self, b64_audio: str) -> str:
        """Sends raw audio bytes to Groq's Whisper API for transcription."""
        if not b64_audio:
            return ""
            
        try:
            # Strip the base64 data URI header if the browser sent it
            if "," in b64_audio:
                b64_audio = b64_audio.split(",")[1]
                
            audio_bytes = base64.b64decode(b64_audio)
            
            # Whisper API needs a tuple with a filename to determine the audio format.
            audio_file = ("audio.webm", audio_bytes, "audio/webm")
            
            response = await self.client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3", # Groq's flagship STT model
                response_format="json",
                language="en",
                temperature=0.0
            )
            
            transcript = response.text.strip()
            print(f"[STT AGENT]: Heard -> '{transcript}'")
            return transcript
            
        except Exception as e:
            print(f"❌ [STT ERROR]: {e}")
            return ""

    async def evaluate_answer(
        self, 
        spoken_answer: str, 
        correct_answer: str, 
        category: str, 
        is_multiple_choice: bool = False
    ) -> bool:
        """Queries Groq Llama 3 to evaluate scientific answer equivalence."""
        
        if not spoken_answer or not spoken_answer.strip():
            print(f"\n[JUDGE AGENT]: Evaluating '' against '{correct_answer}'...")
            print("[JUDGE AGENT]: Result -> False (No answer spoken / empty input)")
            return False

        print(f"\n[JUDGE AGENT]: Evaluating '{spoken_answer}' against '{correct_answer}'...")

        system_prompt = (
            "You are an official National Science Bowl (NSB) Judge. "
            "You must strictly enforce official NSB judging rules without exception.\n\n"
            "OFFICIAL SCIENCE BOWL RULES:\n"
            "1. MULTIPLE CHOICE RULES:\n"
            "   - Acceptable formats: The correct letter choice alone (e.g., 'W'), the exact text alone (e.g., 'stationary'), or both combined (e.g., 'W stationary').\n"
            "   - Conflict Rule: If the student gives a choice letter that contradicts the text they speak (e.g., saying 'X stationary' when 'W' is stationary), mark FALSE.\n\n"
            "2. SHORT ANSWER RULES:\n"
            "   - Must match the scientific term or mathematical value in the answer key.\n"
            "   - Pay strict attention to parenthetical directives in the key:\n"
            "     * Honor '(ACCEPT: ...)' or '[ACCEPT: ...]' directives.\n"
            "     * Honor '(DO NOT ACCEPT: ...)' or '[DO NOT ACCEPT: ...]' directives strictly—if the student gives a forbidden term, mark FALSE.\n\n"
            "3. SPOKEN TRANSCRIPT & CONTRADICTION RULES:\n"
            "   - Speech-To-Text Stutters: Ignore simple acoustic repetitions (e.g., 'oxygen oxygen' = 'oxygen').\n"
            "   - Contradictory Answers: If the student changes their mind or states two different scientific terms (e.g., 'carbon no oxygen'), mark FALSE.\n"
            "   - Silence / Non-answers: Words like 'idk', 'oops', 'huh', or empty input are ALWAYS FALSE.\n\n"
            "OUTPUT REQUIREMENT:\n"
            "Respond strictly in valid JSON format: {\"is_correct\": true/false, \"reason\": \"brief official ruling explanation\"}"
        )

        user_prompt = f"Category: {category}\nOfficial Answer: {correct_answer}\nStudent Spoken Answer: {spoken_answer}"

        try:
            response = await self.client.chat.completions.create(
                model="openai/gpt-oss-20b",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0
            )

            result = json.loads(response.choices[0].message.content)
            print(f"[JUDGE AGENT]: Result -> {result.get('is_correct', False)} ({result.get('reason', '')})")
            return result.get("is_correct", False)

        except Exception as e:
            print(f"[JUDGE AGENT ERROR]: {e}")
            return False