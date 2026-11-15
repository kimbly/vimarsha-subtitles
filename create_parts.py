#!/usr/bin/env python3
import sys
import os

# -----------------------------
# Utilities
# -----------------------------

def timestamp_to_seconds(ts):
    h, m, s = ts.split(":")
    if "." in s:
        s, ms = s.split(".")
    else:
        ms = 0
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000


def parse_vtt(filename):
    cues = []
    with open(filename, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f]

    i = 0
    while i < len(lines):
        if "-->" in lines[i]:
            time_line = lines[i]
            start, end = time_line.split("-->")
            start = start.strip()
            end = end.strip()

            text = []
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                text.append(lines[i])
                i += 1

            cues.append({
                "start": start,
                "end": end,
                "start_sec": timestamp_to_seconds(start),
                "text": "\n".join(text)
            })

        i += 1

    return cues


def clear():
    os.system("cls" if os.name == "nt" else "clear")


# -----------------------------
# Arrow key handling
# -----------------------------

def read_key():
    if os.name == "nt":
        import msvcrt
        c = msvcrt.getch()
        if c == b"\xe0":
            c = msvcrt.getch()
            if c == b"H":
                return "UP"
            if c == b"P":
                return "DOWN"
        if c == b"\r":
            return "ENTER"
    else:
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch1 = sys.stdin.read(1)
            if ch1 == "\x1b":
                ch2 = sys.stdin.read(1)
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "UP"
                if ch3 == "B":
                    return "DOWN"
            if ch1 == "\r":
                return "ENTER"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return None


# -----------------------------
# Display
# -----------------------------

def show_context(cues, idx):
    clear()

    start = max(0, idx - 5)
    end = min(len(cues), idx + 5)

    print("\nBreak occurs BETWEEN the arrows\n")

    for i in range(start, end):

        if i == idx:
            print("--------- BREAK HERE ---------")

        cue = cues[i]
        text = cue["text"].replace("\n", " ")

        print(f"{i:4d}  {cue['start']}  {text[:80]}")

    if idx == end:
        print("--------- BREAK HERE ---------")

    print("\nUse ↑ ↓ arrows to move breakpoint. Press ENTER to confirm.\n")


# -----------------------------
# Initial breakpoint guesses
# -----------------------------

def initial_breaks(cues, parts):
    total = cues[-1]["start_sec"]

    targets = []
    for i in range(1, parts):
        target_time = total * (i / parts)

        best = min(
            range(len(cues)),
            key=lambda j: abs(cues[j]["start_sec"] - target_time)
        )

        targets.append(best)

    return targets


# -----------------------------
# Interactive breakpoint chooser
# -----------------------------

def choose_breaks(cues, parts):

    breaks = initial_breaks(cues, parts)

    for i in range(len(breaks)):

        idx = breaks[i]

        while True:

            show_context(cues, idx)

            key = read_key()

            if key == "UP" and idx > 1:
                idx -= 1

            elif key == "DOWN" and idx < len(cues) - 1:
                idx += 1

            elif key == "ENTER":
                breaks[i] = idx
                break

    return breaks


# -----------------------------
# Write output files
# -----------------------------

def write_parts(cues, breaks):

    points = [0] + breaks + [len(cues)]

    for i in range(len(points) - 1):

        start = points[i]
        end = points[i+1]

        filename = f"part{i+1}.txt"

        with open(filename, "w", encoding="utf-8") as f:

            for cue in cues[start:end]:
                f.write(f"{cue['start']} --> {cue['end']}\n")
                f.write(cue["text"] + "\n\n")

        print("Wrote", filename)


# -----------------------------
# Main
# -----------------------------

def main():

    if len(sys.argv) != 3:
        print("Usage: python split_vtt.py file.vtt parts")
        return

    filename = sys.argv[1]
    parts = int(sys.argv[2])

    cues = parse_vtt(filename)

    print(f"Loaded {len(cues)} cue cards")

    breaks = choose_breaks(cues, parts)

    write_parts(cues, breaks)


if __name__ == "__main__":
    main()