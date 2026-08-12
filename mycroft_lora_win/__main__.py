"""CLI minimale pour tester le paquet hors du core Phoenix."""

import argparse

from ._ps import list_voices
from .tts import WindowsSAPItts


def main() -> None:
    ap = argparse.ArgumentParser(prog="mycroft-lora-win")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-voices", help="Liste les voix TTS installées")

    t = sub.add_parser("tts", help="Synthétise du texte en WAV PCM")
    t.add_argument("text")
    t.add_argument("out")

    args = ap.parse_args()

    if args.cmd == "list-voices":
        for desc in list_voices():
            print(desc)
    elif args.cmd == "tts":
        backend = WindowsSAPItts({"id": "windows"})
        with open(args.out, "wb") as fh:
            for chunk in backend.synthesize(args.text):
                fh.write(chunk)
        print(f"PCM écrit dans {args.out}")


if __name__ == "__main__":
    main()
