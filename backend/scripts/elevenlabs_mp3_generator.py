import os

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.play import save

load_dotenv()

client = ElevenLabs(
    api_key=os.getenv("ELEVENLABS_API_KEY")
)

VOICES = {
    "PM": "cgSgspJ2msm6clMCkdW9",
    "DEV": "JBFqnCBsd6RMkjVDRZzb",
    "DS": "onwK4e9ZLuTAKqWW03F9"
}

conversation = [
    ("PM", "Morning team! I want to review whats left before we release the updated model."),
    ("DEV",
     "Sure. Ive already refactored the data-ingestion pipeline, but training still takes around four hours on Azure."),
    ("DS",
     "Yeah, thats because the preprocessing step is still single-threaded. I can parallelize it with Dask to speed things up."),
    ("PM", "That would be great. How long do you think thatll take?"),
    ("DS", "About one day of work, maybe five story points if we use our usual scale."),
    ("DEV",
     "Once thats done, Ill update the model registry and redeploy through MLflow. Should we include monitoring for drift this time?"),
    ("PM", "Yes, please. Lets add an alert if accuracy drops more than three percent."),
    ("DS", "Got it. Ill also prepare a notebook showing how drift is calculated so QA can validate the numbers."),
    ("DEV", "Perfect. Ill set up the API endpoint and handle the integration tests."),
    ("PM", "Awesome. Lets plan to close all related tickets by Thursday and do a quick demo on Friday."),
]

introduction = [
    ("PM", "Hello, I'm Jessice, ambitious project manager with a passion for AI-driven solutions. "),
    ("DEV", "Hi, I'm Alex, a dedicated software developer specializing in building scalable machine learning systems."),
    ("DS", "Hey, I'm Sam, a data scientist and I know everything about drive business decisions.")
]


def synthesize_line(speaker: str, text: str) -> bytes:
    voice_id = VOICES[speaker]
    audio_iter = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    return b"".join(audio_iter)


full_audio = (synthesize_line(s, t) for s, t in conversation)
save(full_audio, "data/team_meeting.mp3")

for s, t in introduction:
    intro_audio = synthesize_line(s, t)
    save(intro_audio, f"data/intro_{s}.mp3")
