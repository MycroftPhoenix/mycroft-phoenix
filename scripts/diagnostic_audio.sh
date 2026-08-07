#!/bin/bash
# Diagnostic audio complet Phoenix - Linux uniquement
# Utilise 'python3 voice_loop.py --diagnostic' pour une version multi-plateforme

DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$DIR:$DIR/mycroft"

echo "=== Diagnostic Audio Phoenix (Linux ALSA/PulseAudio) ==="
echo "Pour un diagnostic multi-plateforme: python3 voice_loop.py --diagnostic"
echo ""

# 1. Lister tous les devices ALSA
echo "--- Périphériques ALSA ---"
aplay -l 2>/dev/null | head -20
echo ""
arecord -l 2>/dev/null | head -20
echo ""

# 2. PulseAudio sinks/sources
echo "--- PulseAudio Sinks ---"
pactl list short sinks 2>/dev/null
echo ""
echo "--- PulseAudio Sources ---"
pactl list short sources 2>/dev/null
echo ""

# 3. Python sounddevice
echo "--- Sounddevice devices ---"
python3 -c "
import sounddevice as sd
for i, d in enumerate(sd.query_devices()):
    marker = ''
    if d['max_input_channels'] > 0: marker += 'IN'
    if d['max_output_channels'] > 0: marker += 'OUT'
    if marker: print(f'  [{i}] {d[\"name\"]} ({marker})')
" 2>&1

echo ""

# 4. Tester chaque device input avec un niveau sonore
echo "--- Test des entrées ---"
python3 -c "
import sounddevice as sd, numpy as np
for i, d in enumerate(sd.query_devices()):
    if d['max_input_channels'] == 0: continue
    try:
        raw = sd.rec(int(1.0 * d['default_samplerate']), samplerate=int(d['default_samplerate']), channels=1, device=i, dtype='int16')
        sd.wait()
        level = np.max(np.abs(raw))
        marker = 'OK' if level > 50 else 'LOW' if level > 10 else 'SILENT'
        print(f'  [{marker}] [{i}] {d[\"name\"]}: peak={level}')
    except Exception as e:
        print(f'  [ERR] [{i}] {d[\"name\"]}: {e}')
" 2>&1

echo ""
echo "--- Test des sorties (bip 1kHz) ---"
for c in $(aplay -l 2>/dev/null | grep -oP 'card \K[0-9]+' | sort -u); do
    echo -n "  Test card $c: "
    if speaker-test -D plughw:$c,3 -t sine -f 1000 -l 1 -s 1 2>/dev/null | head -3; then
        echo "  envoi sonore..."
    else
        echo "  échec"
    fi
done
