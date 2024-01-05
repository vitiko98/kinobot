#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import abc
from typing import Dict


class Notifier(abc.ABC):
    config: Dict

    @abc.abstractmethod
    def send(self, message, images=None, **kwargs):
        raise NotImplementedError


class DiscordWebhook(Notifier):
    def __init__(self, config):
        pass

    def send(self, message, images=None, **kwargs):
        pass
        # discord://webhook_id/webhook_token
        # discord://avatar@webhook_id/webhook_token       pass
