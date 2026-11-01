"""Probe the local model at a given prompt length.

    python tools/context_probe.py --tokens 16000

Sends one request with a prompt of roughly that many tokens, measures wall time, prompt
throughput, the process working set and the GPU dedicated memory attributed to the model
process, and reports the context the server says it is using. Filler text is generated
locally; no article content is involved.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILLER_PARAGRAPH = (
    "The regional planning office published its quarterly assessment of industrial capacity. "
    "It notes that utilisation rose in three of the five surveyed sectors, that input costs were "
    "broadly flat, and that order backlogs lengthened modestly. The report cautions that the "
    "figures are provisional and will be revised next quarter. Analysts said the release was "
    "consistent with a gradual recovery rather than a sharp rebound. "
)


def api_key():
    for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('OR_LLM_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def filler(target_tokens):
    """Roughly target_tokens tokens of neutral text (about 4 characters per token)."""
    chunk = FILLER_PARAGRAPH
    # Calibrated on this model: about 5.2 characters per token for English prose.
    repeats = max(1, int(target_tokens * 5.2 / len(chunk)) + 1)
    return chunk * repeats


def server_pid():
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
                          "Get-Process llama-server -ErrorAction SilentlyContinue | "
                          "Select-Object -First 1 -ExpandProperty Id"],
                         capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


def working_set_mb(pid):
    if not pid:
        return None
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
                          f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).WorkingSet64"],
                         capture_output=True, text=True)
    try:
        return round(int(out.stdout.strip()) / 1048576, 1)
    except ValueError:
        return None


def gpu_memory_mb(pid):
    """Dedicated GPU memory of one process, from the Windows GPU performance counters."""
    if not pid:
        return None
    command = ("((Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue)"
               ".CounterSamples | Where-Object { $_.InstanceName -like '*pid_%d_*' } | "
               "Measure-Object -Property CookedValue -Sum).Sum" % pid)
    out = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip()) / 1048576, 1)
    except ValueError:
        return None


def call(prompt, max_tokens, timeout):
    key = api_key()
    body = json.dumps({'model': 'default', 'max_tokens': max_tokens, 'temperature': 0,
                       'messages': [{'role': 'user', 'content': prompt}]}).encode()
    request = urllib.request.Request('http://127.0.0.1:8080/v1/chat/completions', data=body,
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer ' + key}, method='POST')
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    return payload, time.time() - started


def probe(target_tokens, max_tokens=16, timeout=3600):
    pid = server_pid()
    before = {'rss_mb': working_set_mb(pid), 'gpu_mb': gpu_memory_mb(pid)}
    prompt = filler(target_tokens) + "\n\nAnswer with the single word: ready"
    result = {'target_tokens': target_tokens, 'pid': pid, 'before': before}
    try:
        payload, wall = call(prompt, max_tokens, timeout)
        usage = payload.get('usage') or {}
        prompt_tokens = usage.get('prompt_tokens') or 0
        completion = usage.get('completion_tokens') or 0
        result.update({
            'ok': True, 'wall_seconds': round(wall, 1),
            'prompt_tokens': prompt_tokens, 'completion_tokens': completion,
            'prompt_tokens_per_second': round(prompt_tokens / wall, 1) if wall else None,
            'reply': (payload['choices'][0]['message']['content'] or '').strip()[:40],
        })
    except Exception as exc:
        result.update({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:200]})
    time.sleep(2)
    result['after'] = {'rss_mb': working_set_mb(pid), 'gpu_mb': gpu_memory_mb(pid)}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Probe the local model at a prompt length')
    parser.add_argument('--tokens', type=int, nargs='+', default=[2000])
    parser.add_argument('--max-tokens', type=int, default=16)
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--out', default='')
    args = parser.parse_args(argv)
    results = [probe(n, args.max_tokens, args.timeout) for n in args.tokens]
    text = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
