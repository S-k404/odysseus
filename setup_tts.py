import sys
import os

# Append the directory so we can import from core.database
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.database import SessionLocal, ModelEndpoint
from src.settings import load_settings, save_settings
import uuid

def setup_tts():
    db = SessionLocal()
    try:
        # Check if Kokoro is already there
        endpoint = db.query(ModelEndpoint).filter(ModelEndpoint.name == "Kokoro TTS").first()
        if not endpoint:
            endpoint_id = "kokoro_tts_" + uuid.uuid4().hex[:8]
            endpoint = ModelEndpoint(
                id=endpoint_id,
                name="Kokoro TTS",
                base_url="http://kokoro-tts:8880/v1",
                api_key="sk-no-key",
            )
            db.add(endpoint)
            db.commit()
            print(f"Added Kokoro TTS endpoint with ID: {endpoint_id}")
        else:
            endpoint_id = endpoint.id
            print(f"Kokoro TTS endpoint already exists with ID: {endpoint_id}")
        
        # Update settings
        settings = load_settings()
        settings["tts_enabled"] = True
        settings["tts_provider"] = f"endpoint:{endpoint_id}"
        # Kokoro models and voices usually map to specific strings. For Kokoro-FastAPI, model=kokoro, voice=af_heart (default)
        settings["tts_model"] = "kokoro"
        settings["tts_voice"] = "af_heart"
        settings["tts_speed"] = "1"
        save_settings(settings)
        print("Updated TTS settings to use Kokoro TTS.")
        
    finally:
        db.close()

if __name__ == "__main__":
    setup_tts()
