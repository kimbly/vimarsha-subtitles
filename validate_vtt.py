import re
import sys
from pathlib import Path

USAGE = "Usage: python validate_vtt.py <webvtt-file>"

TS_LINE_RE = re.compile(
    r"^\s*(?P<start>\S+)\s*-->\s*(?P<end>\S+)(?:\s+.*)?\s*$"
)
TS_RE = re.compile(
    r"^(?:(?P<h>\d+):)?(?P<m>\d{2}):(?P<s>\d{2})(?:[.,](?P<ms>\d{1,3}))?$"
)


def parse_timestamp(value: str):
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if "," in text:
        # Comma is not valid in WebVTT milliseconds; it is a common issue to report.
        text = text.replace(",", ".")
    m = TS_RE.fullmatch(text)
    if not m:
        raise ValueError(f"malformed timestamp: {value!r}")
    hours = int(m.group("h") or 0)
    minutes = int(m.group("m"))
    seconds = int(m.group("s"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"timestamp has invalid minute or second component: {value!r}")
    milliseconds = 0
    ms_text = m.group("ms")
    if ms_text is not None:
        milliseconds = int(ms_text)
        if len(ms_text) == 1:
            milliseconds *= 100
        elif len(ms_text) == 2:
            milliseconds *= 10
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def split_blocks(lines):
    blocks = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def format_timestamp(total_seconds: float, original: str = "") -> str:
    total_ms = int(round(total_seconds * 1000))
    hours, remainder = divmod(total_ms, 3600 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    seconds, milliseconds = divmod(remainder, 1000)
    text = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    if ":" not in original or original.count(":") < 2:
        text = f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return text


def fix_vtt_text(text: str):
    lines = text.splitlines()
    if not lines:
        return ""

    blocks = split_blocks(lines)
    fixed_blocks = []
    if blocks and blocks[0] and blocks[0][0].strip().startswith("WEBVTT"):
        header = blocks[0][:]
        fixed_blocks.append(header)
        blocks = blocks[1:]
    else:
        fixed_blocks.append(["WEBVTT"])

    previous_end = None
    for block in blocks:
        if not block:
            continue

        if block[0].strip().startswith(("NOTE", "STYLE", "REGION")):
            fixed_blocks.append(block)
            continue

        fixed_block = []
        for line in block:
            fixed_block.append(line)

        for i, line in enumerate(block):
            ts_match = TS_LINE_RE.match(line)
            if not ts_match:
                continue

            start_text = ts_match.group("start")
            end_text = ts_match.group("end")
            raw_start = start_text
            raw_end = end_text
            if "," in start_text:
                start_text = start_text.replace(",", ".")
            if "," in end_text:
                end_text = end_text.replace(",", ".")

            start = None
            end = None
            try:
                start = parse_timestamp(start_text)
            except ValueError:
                pass
            try:
                end = parse_timestamp(end_text)
            except ValueError:
                pass

            if previous_end is not None and start is not None and end is not None:
                if start < previous_end and previous_end >= 55 * 60 and start < 5 * 60:
                    start += 3600
                    end += 3600

            if start is not None and end is not None:
                previous_end = end

            new_start = raw_start
            new_end = raw_end
            if start is not None:
                new_start = format_timestamp(start, raw_start)
            if end is not None:
                new_end = format_timestamp(end, raw_end)

            before = line[:ts_match.start("start")]
            after = line[ts_match.end("end"):]
            fixed_block[i] = f"{before}{new_start} --> {new_end}{after}"

        fixed_blocks.append(fixed_block)

    output = []
    for idx, block in enumerate(fixed_blocks):
        if idx > 0 and block and output and output[-1] != "":
            output.append("")
        output.extend(block)
        if idx < len(fixed_blocks) - 1:
            output.append("")

    # ensure a trailing newline for clean file output
    text_out = "\n".join(output)
    if text_out and not text_out.endswith("\n"):
        text_out += "\n"
    return text_out


def read_fixed_vtt(path: str):
    p = Path(path)
    try:
        original = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None

    if not original.strip():
        return None

    fixed = fix_vtt_text(original)
    if fixed == original:
        return None

    return fixed


def validate_vtt(path: str):
    issues = []
    p = Path(path)

    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return [f"unable to read file: {exc}"]

    if not text.strip():
        return ["file is empty"]

    lines = text.splitlines()
    if not lines:
        return ["file is empty"]

    first_nonempty = next((line.strip() for line in lines if line.strip()), "")
    if not first_nonempty.startswith("WEBVTT"):
        issues.append("missing WEBVTT header")

    blocks = split_blocks(lines)
    if blocks and blocks[0] and blocks[0][0].strip().startswith("WEBVTT"):
        blocks = blocks[1:]

    previous_end = None
    cue_number = 0

    for block in blocks:
        if not block:
            continue

        if block[0].strip().startswith(("NOTE", "STYLE", "REGION")):
            continue

        cue_number += 1
        timestamp_lines = [line for line in block if "-->" in line]

        if not timestamp_lines:
            issues.append(f"cue {cue_number}: missing timestamp line")
            continue

        if len(timestamp_lines) > 1:
            issues.append(f"cue {cue_number}: multiple timestamp lines in one cue")

        for line in block:
            if re.search(r"\d{2}:\d{2}:\d{2},\d{1,3}", line) or re.search(r"\d{2}:\d{2},\d{1,3}", line):
                issues.append(f"cue {cue_number}: timestamp uses a comma instead of a decimal point: {line.strip()}")

        for ts_line in timestamp_lines:
            match = TS_LINE_RE.match(ts_line)
            if not match:
                issues.append(f"cue {cue_number}: malformed cue timing line: {ts_line.strip()}")
                continue

            start_text = match.group("start")
            end_text = match.group("end")

            try:
                start = parse_timestamp(start_text)
            except ValueError as exc:
                issues.append(f"cue {cue_number}: invalid start timestamp '{start_text}': {exc}")
                start = None

            try:
                end = parse_timestamp(end_text)
            except ValueError as exc:
                issues.append(f"cue {cue_number}: invalid end timestamp '{end_text}': {exc}")
                end = None

            if start is not None and end is not None:
                if end <= start:
                    issues.append(
                        f"cue {cue_number}: zero or negative duration: {start_text} --> {end_text}"
                    )
                if previous_end is not None:
                    if start < previous_end:
                        issues.append(
                            f"cue {cue_number}: non-monotonic timestamps: {start_text} starts before previous cue ended at {previous_end:.3f}s"
                        )
                    elif start - previous_end > 120:
                        issues.append(
                            f"cue {cue_number}: gap greater than 2 minutes: previous cue ended at {previous_end:.3f}s, next cue starts at {start:.3f}s"
                        )
                previous_end = end

    return issues


def main():
    if len(sys.argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2

    path = sys.argv[1]
    issues = validate_vtt(path)
    fixed_path = None

    if issues:
        fixed_output = read_fixed_vtt(path)
        if fixed_output is not None:
            fixed_path = f"{path}.fixed"
            Path(fixed_path).write_text(fixed_output, encoding="utf-8")

    if issues:
        print(f"Validation failed for {path}:")
        for issue in issues:
            print(f"- {issue}")
        if fixed_path:
            print(f"Suggested fixed file written to: {fixed_path}")
        return 1

    print(f"OK: {path} has no detected WebVTT issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
