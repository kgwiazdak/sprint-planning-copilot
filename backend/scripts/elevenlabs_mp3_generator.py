import os

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.play import save

load_dotenv()

client = ElevenLabs(
    api_key=os.getenv("ELEVENLABS_API_KEY")
)

VOICES = {
    "Adrian_Puchacki": "cgSgspJ2msm6clMCkdW9",
    # Waldemar: keep a neutral/mid male voice (override with WALDEMAR_WALASIK_VOICE_ID if desired).
    "Waldemar_Walasik": os.getenv("WALDEMAR_WALASIK_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"),
    # Wojciech: use a very different timbre (default to a brighter/female voice) to maximize separation.
    "Wojciech_Puczyk": os.getenv("WOJCIECH_PUCZYK_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
}

conversation = [
    ("Adrian_Puchacki", "Morning team, let's keep this simple. We need four tasks and clear owners."),
    ("Waldemar_Walasik", "Morning. Training still takes four hours on Azure, even after the ingest refactor."),
    ("Wojciech_Puczyk", "I can parallelize preprocessing with Dask. Nice and clear: that would be my task."),
    ("Adrian_Puchacki", "Great, Wojciech owns Dask parallelization. How many points would that be?"),
    ("Wojciech_Puczyk", "Let's vote it at 5 points. It's mostly wiring and testing."),
    ("Adrian_Puchacki", "Done. Task one: Wojciech, Dask parallelization, 5 points."),
    ("Waldemar_Walasik", "After that, I will update the model registry and redeploy via MLflow. That's my task."),
    ("Adrian_Puchacki", "How many points do you want for the registry and redeploy, Waldemar?"),
    ("Waldemar_Walasik", "Call it 3 points. Small changes and smoke tests."),
    ("Adrian_Puchacki", "Good. Task two: Waldemar, registry update plus redeploy, 3 points."),
    ("Adrian_Puchacki", "We also need drift detection and alerting. Waldemar, do you want that too?"),
    ("Waldemar_Walasik", "Yes, I'll take drift alerts. Simple rule: alert if accuracy drops more than three percent."),
    ("Adrian_Puchacki", "Points for drift alerting?"),
    ("Waldemar_Walasik", "3 points is fine, includes Slack notification and MLflow log."),
    ("Adrian_Puchacki", "Task three: Waldemar, drift detection and alerting, 3 points."),
    ("Wojciech_Puczyk", "Do we need a release brief for stakeholders?"),
    ("Adrian_Puchacki", "Yes, I'll own the release-readiness checklist and brief. Very small."),
    ("Waldemar_Walasik", "How many points for your brief, Adrian?"),
    ("Adrian_Puchacki", "1 point. Just making sure it's tracked."),
    ("Adrian_Puchacki", "Task four: Adrian, release brief and checklist, 1 point."),
    ("Wojciech_Puczyk", "Recap so we don't mess it up: I own Dask parallelization, 5 points."),
    ("Waldemar_Walasik", "I own registry plus redeploy for 3 points, and drift alerting for 3 points."),
    ("Adrian_Puchacki", "And I own the release brief at 1 point. Four tasks total, owners clear."),
    ("Wojciech_Puczyk", "Timeline: finish by Thursday, quick demo Friday. Let's keep it simple."),
    ("Waldemar_Walasik", "No extra tasks hiding here. Just these four."),
    ("Adrian_Puchacki", "Perfect. Thanks—execute and update the board."),
]

introduction = [
    ("Adrian_Puchacki", "Hello, I'm Adrian Puchacki, ambitious project manager with a passion for AI-driven solutions. In my free time I like to play football, read books and hiking. I think I'm really good suited for that job as I'm keen to help everybody"),
    ("Waldemar_Walasik", "Hi, I'm Waldemar Walasik, a dedicated software developer specializing in building scalable machine learning systems. I like basketball, comics and my favourite sitcom is Friends. I'm new technology enjoyer and I know everything about crypto."),
    ("Wojciech_Puczyk", "Hey, I'm Wojciech Puczyk, a data scientist and I know everything about drive business decisions. 2 years ago I did my first marathon and now it's my passion. I'm running everyday and preparing to run a marathon in every continent in the world.")
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
save(full_audio, "data/newest.mp3")

for s, t in introduction:
    intro_audio = synthesize_line(s, t)
    save(intro_audio, f"data/intro_{s}.mp3")
