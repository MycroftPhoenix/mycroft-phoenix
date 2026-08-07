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
"""Mycroft util library.

Allégé pour Phoenix : n'importe plus les modules legacy Mycroft-core
(format, parse, audio_utils, signal, process_utils, mycroft.audio...)
qui tirent des dépendances lourdes et mortes (adapt, padatious, pyaudio
obligatoire, lingua_franca, messagebus...). Les sous-modules restent
accessibles par import direct (from mycroft.util.log import LOG).
"""
from __future__ import absolute_import

import os

from .string_utils import camel_case_split
from .log import LOG

from .data_dirs import get_data_dir, get_kuzu_path
