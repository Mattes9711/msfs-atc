"""Spike (step 4): pyttsx3 voices, ICAO numbers, and speaking from a worker thread so the main loop never blocks."""
import argparse
import queue
import threading
import time

import pyttsx3

PHRASES = [
    "D L H four alpha bravo, runway two seven, cleared for takeoff, wind two six zero degrees one two knots.",
    "Climb flight level one two zero, squawk four seven two one.",
    "Contact departure one one niner decimal eight seven fife.",
    "QNH one zero one tree, information bravo.",
]


class Speaker:
    def __init__(self, voice_index, rate):
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, args=(voice_index, rate), daemon=True)
        self.thread.start()

    def _run(self, voice_index, rate):
        import comtypes

        comtypes.CoInitialize()  # SAPI is COM; a non-main thread must init COM itself
        engine = make_engine(voice_index, rate)
        while (text := self.queue.get()) is not None:
            engine.say(text)
            engine.runAndWait()
            self.queue.task_done()

    def say(self, text):
        self.queue.put(text)

    def wait(self):
        self.queue.join()


def make_engine(voice_index, rate):
    engine = pyttsx3.init()
    if voice_index is not None:
        engine.setProperty("voice", engine.getProperty("voices")[voice_index].id)
    if rate is not None:
        engine.setProperty("rate", rate)
    return engine


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list-voices", action="store_true")
    p.add_argument("--voice", type=int)
    p.add_argument("--rate", type=int)
    p.add_argument("--save", help="write the phrases to this wav file instead of speaking")
    args = p.parse_args()

    if args.list_voices:
        for i, v in enumerate(pyttsx3.init().getProperty("voices")):
            print(i, v.name, v.id)
        return
    if args.save:
        engine = make_engine(args.voice, args.rate)
        engine.save_to_file(" ".join(PHRASES), args.save)
        engine.runAndWait()
        print(f"Saved {args.save}")
        return

    speaker = Speaker(args.voice, args.rate)
    for phrase in PHRASES:
        speaker.say(phrase)
    done = threading.Thread(target=speaker.wait)
    done.start()
    while done.is_alive():
        print("main loop still running...")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
