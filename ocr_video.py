#!/usr/bin/env python3
"""
ocr_video.py — รันบน physics server (GPU)
Usage: python3 ocr_video.py <mu_video_*.mp4> [--max-frames N]
Output: CSV ชื่อเดียวกับ video ใน directory เดียวกัน

ROI order in video (top→bottom):
  0: mu1_mu2_roi
  1: mu_rate_roi
  2: progress_roi
"""
import sys, os, re, csv, warnings
from datetime import datetime, timedelta
import cv2

ROI_NAMES = ['mu1_roi', 'mu2_roi', 'mu_rate_roi', 'progress_roi']
CROP_H    = 80   # must match _REC_CROP_H in video_window.py


# ── validation ────────────────────────────────────────────────────────────────

def _to_float(text):
    if not text:
        return None
    try:
        return float(re.sub(r'[^\d.]', '', text))
    except ValueError:
        return None

def validate_mu(text):
    n = _to_float(text)
    if n is None: return None
    if 100 <= n <= 40000: return n
    if n > 1000000:
        s = str(int(n))
        if len(s) >= 7:
            try:
                c = float(s[:2] + s[2:5] + '.' + s[5:7])
                if 100 <= c <= 40000: return c
            except Exception: pass
    return None

def validate_mu_rate(text):
    n = _to_float(text)
    if not n: return None
    if 10000 <= n <= 300000: return n
    if 100000 <= n <= 3000000:
        c = n / 10
        if 10000 <= c <= 300000: return c
    return None

def validate_progress(text):
    n = _to_float(text)
    if n is None: return None
    if 0 <= n <= 100: return n
    if n > 100:
        alt = re.sub(r'(\d)\s+(\d)', r'\1.\2', text or '')
        n2 = _to_float(alt)
        if n2 and 0 <= n2 <= 100: return n2
    return None


# ── main ──────────────────────────────────────────────────────────────────────

def process(video_path, max_frames=None):
    print('[ocr_video] loading EasyOCR…')
    import PIL.Image
    if not hasattr(PIL.Image, 'Resampling'):
        PIL.Image.Resampling = PIL.Image
    import easyocr, torch
    gpu = torch.cuda.is_available()
    print(f'[ocr_video] GPU={gpu} ({torch.cuda.get_device_name(0) if gpu else "none"})')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        reader = easyocr.Reader(['en'], gpu=gpu)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f'[ocr_video] ERROR: cannot open {video_path}')
        return

    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f'[ocr_video] {total} frames @ {fps:.1f} fps')

    m = re.search(r'(\d{8}_\d{6})', os.path.basename(video_path))
    start_dt = datetime.strptime(m.group(1), '%Y%m%d_%H%M%S') if m else None

    out_path = os.path.splitext(video_path)[0] + '_ocr.csv'
    rows = []

    def ocr(strip, scale=2):
        h, w = strip.shape[:2]
        big = cv2.resize(strip, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
        return [r[1] for r in reader.readtext(big)]

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if max_frames and frame_idx >= max_frames:
            break
        frame_idx += 1
        t_sec = frame_idx / fps

        mu1_texts  = ocr(frame[0        : CROP_H,   :], scale=4)
        mu2_texts  = ocr(frame[CROP_H   : CROP_H*2, :], scale=4)
        rate_texts = ocr(frame[CROP_H*2 : CROP_H*3, :])
        prog_texts = ocr(frame[CROP_H*3 : CROP_H*4, :])

        mu1  = validate_mu(mu1_texts[0] if mu1_texts else None)
        mu2  = validate_mu(mu2_texts[0] if mu2_texts else None)
        rate = validate_mu_rate(rate_texts[0] if rate_texts else None)
        prog = validate_progress(prog_texts[0] if prog_texts else None)

        dt_str = (start_dt + timedelta(seconds=t_sec)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if start_dt else None
        rows.append({
            'frame': frame_idx, 'time_sec': round(t_sec, 3), 'datetime': dt_str,
            'mu1': mu1, 'mu2': mu2, 'mu_rate': rate, 'progress': prog,
        })

        if frame_idx % 100 == 0 or mu1 or mu2 or rate or prog:
            print(f'[f{frame_idx}/{total}] mu1={mu1} mu2={mu2} rate={rate} prog={prog}')

    cap.release()

    if not rows:
        print('[ocr_video] no frames processed')
        return
    with open(out_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f'[ocr_video] done → {out_path}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 ocr_video.py <mu_video_*.mp4> [--max-frames N]')
        sys.exit(1)
    max_f = None
    if '--max-frames' in sys.argv:
        idx = sys.argv.index('--max-frames')
        max_f = int(sys.argv[idx + 1])
    process(sys.argv[1], max_frames=max_f)
