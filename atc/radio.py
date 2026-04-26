"""Radio queue and phraseology generator.

A single global voice channel: only one transmission is "spoken" at a time.
Each transmission stays on screen for ~3.5 seconds. Player commands and
aircraft readbacks are queued; the queue drains in order.
"""
from collections import deque

DISPLAY_SECONDS = 3.5
HISTORY_LIMIT = 30


class RadioMessage:
    def __init__(self, source, text):
        self.source = source  # "ATC", or callsign of speaker
        self.text = text


class RadioManager:
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.timer = 0.0
        self.history = []

    # ------------------------------------------------------------- core API
    def transmit(self, source, text):
        self.queue.append(RadioMessage(source, text))

    def update(self, dt):
        if self.current is None and self.queue:
            self.current = self.queue.popleft()
            self.timer = DISPLAY_SECONDS
            self.history.append(self.current)
            if len(self.history) > HISTORY_LIMIT:
                self.history.pop(0)
        elif self.current is not None:
            self.timer -= dt
            if self.timer <= 0:
                self.current = None

    # --------------------------------------------- ATC -> aircraft sentences
    @staticmethod
    def atc_climb(callsign, altitude):
        return f"{callsign}, climb and maintain {altitude} feet."

    @staticmethod
    def atc_descend(callsign, altitude):
        return f"{callsign}, descend and maintain {altitude} feet."

    @staticmethod
    def atc_speed(callsign, knots):
        return f"{callsign}, keep speed not above {knots} knots."

    @staticmethod
    def atc_clear_to_land(callsign, runway):
        return f"{callsign}, cleared to land runway {runway}."

    @staticmethod
    def atc_wind(callsign, wind_dir, wind_speed):
        return f"{callsign}, wind {wind_dir:03d} degrees at {wind_speed} knots."

    @staticmethod
    def atc_handoff(callsign, target, frequency):
        return f"{callsign}, contact {target} on {frequency}."

    @staticmethod
    def atc_go_around(callsign):
        return f"{callsign}, go around, I say again, go around."

    @staticmethod
    def atc_hold(callsign):
        return f"{callsign}, hold over present position."

    # --------------------------------------------- aircraft -> ATC readbacks
    @staticmethod
    def rb_climb(callsign, altitude):
        return f"Climbing to {altitude} feet, {callsign}."

    @staticmethod
    def rb_descend(callsign, altitude):
        return f"Descending to {altitude} feet, {callsign}."

    @staticmethod
    def rb_speed(callsign, knots):
        return f"Speed not above {knots} knots, {callsign}."

    @staticmethod
    def rb_clear_to_land(callsign, runway):
        return f"Cleared to land runway {runway}, {callsign}."

    @staticmethod
    def rb_wind(callsign):
        return f"Copy, {callsign}."

    @staticmethod
    def rb_handoff(callsign, target, frequency):
        return f"Contacting {target} on {frequency}, {callsign}."

    @staticmethod
    def rb_go_around(callsign):
        return f"Going around, {callsign}."

    @staticmethod
    def rb_hold(callsign):
        return f"Holding over present position, {callsign}."

    # --------------------------------------------- emergency calls (aircraft)
    @staticmethod
    def call_minimum_fuel(callsign):
        return f"{callsign}, minimum fuel."

    @staticmethod
    def call_mayday_fuel(callsign):
        return f"Mayday, mayday, mayday, {callsign}, fuel emergency."

    @staticmethod
    def call_engine_failure(callsign):
        return f"{callsign} mayday, mayday, mayday, lost thrust in Engine 1."
