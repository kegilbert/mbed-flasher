"""
Copyright 2016 ARM Limited

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import logging

class Logger(object):

    def __init__(self, name):
        self.logger = logging.getLogger(name)
        if len(self.logger.handlers) == 0:
            self.logger.addHandler(logging.NullHandler())
            self.logger.setLevel(logging.ERROR)
            self.logger.propagate = False
            self.logger.info('No logger supplied, using default logging logger')

    def __call__(self, name):    
        return self.logger
