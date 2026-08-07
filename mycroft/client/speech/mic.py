# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import sounddevice as sd
import numpy as np
import speech_recognition as sr
from collections import deque
import threading
import datetime
import os
from tempfile import gettempdir


class MutableStream(sd.Stream):
    def __init__(self, samplerate=16000, blocksize=1024, device=None, channels=1, dtype='int16', 
                 callback=None, finished_callback=None, mute=False):
        super().__init__(samplerate=samplerate, blocksize=blocksize, device=device, channels=channels, dtype=dtype, callback=callback, finished_callback=finished_callback)
        self.muted = False
        if mute:
            self.mute()

    def mute(self):
        self.muted = True
        self.stop()

    def unmute(self):
        self.muted = False
        self.start()

class MutableMicrophone(sr.Microphone):
    def __init__(self, device_index=None, sample_rate=16000, chunk_size=1024,
                 mute=False):
        self.muted = False
        if mute: 
            self.mute()
        super().__init__(sample_rate=sample_rate, chunk_size=chunk_size)

    def __enter__(self):
        self.audio = sd
        self.stream = MutableStream(samplerate=self.SAMPLE_RATE, blocksize=self.CHUNK, device=self.device_index, channels=1, dtype='int16', mute=self.muted)
        self.stream.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stream.stop()
        self.stream = None

    def mute(self):
        self.muted = True
        if self.stream:
            self.stream.mute()

    def unmute(self):
        self.muted = False
        if self.stream:
            self.stream.unmute()

    def is_muted(self):
        return self.muted


class ResponsiveRecognizer(sr.Recognizer):
    # Padding of silence when feeding to pocketsphinx
    SILENCE_SEC = 0.01

    # The minimum seconds of noise before a
    # phrase can be considered complete
    MIN_LOUD_SEC_PER_PHRASE = 0.5

    # The minimum seconds of silence required at the end
    # before a phrase will be considered complete
    MIN_SILENCE_AT_END = 0.25

    # Time between pocketsphinx checks for the wake word
    SEC_BETWEEN_WW_CHECKS = 0.2

    def __init__(self, wake_word_recognizer, watchdog=None):
        self._watchdog = watchdog or (lambda: None)  # Default to dummy func
        super().__init__()
        self.wake_word_recognizer = wake_word_recognizer
        self.stream = sd.InputStream(callback=self.callback)
        self.stream.start()
        self.overflow_exc = False

    def callback(self, indata, frames, time, status):
        if status:
            print(status, flush=True)

        # Convert the input data to float
        indata_float = np.array(indata, dtype='float32')

        # Process the audio data
        self.wake_word_recognizer.update(indata_float)

    def record_phrase(self):
        # Placeholder for recording a phrase
        pass

class WakeWordPocketSphinx():
    """
    Interface to PocketSphinx
    """

    def __init__(self, config):
        self.config = config
        self.chunk_size = config.get('chunk_size', 2048)
        self.key_phrase = config['keyword']
        self.hotword_dir = config.get('hotwords_dir', '/res/text/keyword_files')
        self.language = config.get('language', 'en-us')

        # Adjust threshold based on sensitivity setting
        self.key_phrase_threshold = config.get('threshold', 1e-20)

        # PocketSphinx engine
        self.runner = None

    def update(self, chunk):
        """Update the engine with a chunk of audio."""
        if not self.runner:
            return
        # Process the audio chunk
        self.runner.update(chunk)

    def found_wake_word(self, data):
        """Check if the wake word was found in the audio data."""
        if not self.runner:
            return False

        # Don't bother unless we have a full chunk to check
        if len(data) < self.chunk_size:
            return False

        # Perform detection
        return self.runner.found_keyword()

# Load precise hotword as default wake word engine
from precise_runner import PreciseRunner

class Listener(object):
    def __init__(self):
        self.config = {'wake_word_threshold': 1e-90}  # Dummy config
        self.engine = 'pocketsphinx'  # Default engine
        self.engine_config = {'keyword': 'hey mycroft'}  # Dummy engine config
        self.wake_word_recognizer = None
        self.sample_rate = 16000  # Dummy sample rate

        # create the wake word recognizer
        self._load_wake_word_recognizer()

    def _load_wake_word_recognizer(self):
        if self.engine == 'pocketsphinx':
            self.wake_word_recognizer = WakeWordPocketSphinx(self.engine_config)
        elif self.engine == 'precise':
            self.wake_word_recognizer = PreciseRunner(
                self.engine_config.get('model'),
                sensitivity=self.engine_config.get('sensitivity', 0.5),
                trigger_level=self.engine_config.get('trigger_level', 3),
                chunk_size=2048  # Dummy chunk size
            )
        else:
            print('Unknown wake word engine:', self.engine)

    def stop(self):
        pass

    def listen(self):
        # Placeholder for listening function
        pass

# Create a listener instance
listener = Listener()

# Start listening
recognizer = ResponsiveRecognizer(listener.wake_word_recognizer)
try:
    while True:
        pass
except KeyboardInterrupt:
    print("Interrupted by user")
finally:
    recognizer.stream.stop()
    recognizer.stream.close()
