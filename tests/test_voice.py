"""
Test complet : Audio → Pipeline → Audio
"""

import sys
import os

# Setup path
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)
sys.modules['mycroft'] = type(sys)('mycroft')
sys.modules['mycroft'].__path__ = [os.path.join(base_dir, 'mycroft')]

import logging
logging.basicConfig(level=logging.INFO)

from mycroft.pipeline import PhoenixPipeline
from mycroft.audio_processor import AudioProcessor

def test_text_mode():
    """Test en mode texte (pas de micro)."""
    print("\n" + "="*60)
    print("PHOENIX - Test Mode Texte")
    print("="*60 + "\n")
    
    pipeline = PhoenixPipeline(base_dir)
    pipeline.initialize()
    
    # Test cases
    tests = [
        "Bonjour",
        "Quelle heure est-il",
        "Comment tu t'appelles",
        "Merci beaucoup",
        "Au revoir",
        "Quelle est la capitale de la France",
    ]
    
    for text in tests:
        result = pipeline.process(text)
        print(f"👤 {text}")
        print(f"🎯 Intent: {result['intent']['intent']} ({result['intent']['confidence']:.2f})")
        if result['entities']:
            print(f"🔍 Entités: {result['entities']}")
        if result['safety']['triggered']:
            print(f"🛡️ SÉCURITÉ: {result['safety']['type']}")
        print(f"🤖 {result['response']}")
        print()

def test_audio_mode():
    """Test avec micro (si pyaudio dispo)."""
    print("\n" + "="*60)
    print("PHOENIX - Test Mode Audio")
    print("="*60 + "\n")
    
    try:
        import pyaudio
    except ImportError:
        print("❌ pyaudio non installé: pip install pyaudio")
        return
    
    pipeline = PhoenixPipeline(base_dir)
    pipeline.initialize()
    
    audio = AudioProcessor()
    
    print("🎙️ Parlez (5 secondes)...")
    text = audio.record_and_transcribe(duration=5)
    
    if not text:
        print("❌ Rien compris")
        return
        
    print(f"👤 Vous: {text}")
    
    result = pipeline.process(text)
    print(f"🎯 Intent: {result['intent']['intent']}")
    print(f"🤖 Réponse: {result['response']}")
    
    # Synthétiser et jouer
    print("🔊 Lecture...")
    audio.synthesize_and_play(result['response'])

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', action='store_true', help='Mode audio (micro)')
    args = parser.parse_args()
    
    if args.audio:
        test_audio_mode()
    else:
        test_text_mode()