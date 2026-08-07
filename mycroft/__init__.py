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
from os.path import abspath, dirname, join

MYCROFT_ROOT_PATH = abspath(join(dirname(__file__), '..'))

# Tous les imports sont desactivees pour eviter les dependances lourdes
# Charger uniquement ce qui est necessaire via import direct
Api = None
Message = None
adds_context = removes_context = None
MycroftSkill = FallbackSkill = None
intent_handler = intent_file_handler = None
AdaptIntent = None
LOG = None

__all__ = ['MYCROFT_ROOT_PATH',
           'Api',
           'Message',
           'adds_context',
           'removes_context',
           'MycroftSkill',
           'FallbackSkill',
           'intent_handler',
           'intent_file_handler',
           'AdaptIntent']
