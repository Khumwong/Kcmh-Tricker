# remote_scripts/ — server-side processing scripts

ทุกไฟล์ `*.py` / `*.md` ในโฟลเดอร์นี้ถูก `RsyncManager` ส่งขึ้น server ไปไว้ที่
`<remote_path>/scripts/` อัตโนมัติตอนกด connect rsync ใน GUI
(ดู [`modules/rsync_manager.py`](../modules/rsync_manager.py) `_do_connect`).

เพิ่มสคริปต์ server ตัวใหม่ = วางไฟล์ `.py` ในโฟลเดอร์นี้ พอ ไม่ต้องแก้โค้ดที่อื่น

Python บน server: `~/sutpct-env/bin/python3` (มี pyeudaq, uproot, easyocr, torch, psutil)

Layout ปลายทางบน server:

```
<remote_path>/
├── raw/      run*.raw            ← rsync จาก GUI
├── root/     run*.root           ← StdEventMonitor_fast.py สร้าง
├── log/      run*.log            ← program log + tee ของ conversion
├── gating/   run*_gating.csv     ← \xFE/\xEF + Zaber position จาก GUI
├── video/    mu_video_*.mp4      ← scp จาก GUI
└── scripts/  ← โฟลเดอร์นี้ทั้งหมด
```

---

## 1. `StdEventMonitor_fast.py` — raw → ROOT

แปลงไฟล์ EUDAQ `.raw` ไฟล์เดียวเป็น ROOT histogram แยกตาม plane (ขนานด้วย `mp.Pool`)

```bash
~/sutpct-env/bin/python3 StdEventMonitor_fast.py <raw_file> -o <output.root>
```

| อาร์กิวเมนต์ | ความหมาย |
|---|---|
| `raw_file` | ไฟล์ `.raw` อินพุต (บังคับ) |
| `-o, --output` | ROOT เอาต์พุต (ดีฟอลต์: เปลี่ยนนามสกุล `.raw` → `.root`) |
| `--nplanes N` | จำนวน plane เริ่มต้น (ดีฟอลต์ 6) |
| `--workers N` | จำนวน worker process (ดีฟอลต์ `min(nplanes, cpu_count)`) |

ปกติ **ไม่ต้องเรียกตรง** — GUI สั่งผ่าน `run_with_stats.py` ให้อยู่แล้ว
ถ้า log ขึ้น `No valid planes found` แปลว่ามี DAQ plane หลุดกลางรัน (ดู ITS3 Activity log)

## 2. `run_with_stats.py` — wrapper ของข้อ 1 + เก็บสถิติ

รัน `StdEventMonitor_fast.py` (ไฟล์เดียวกันในโฟลเดอร์นี้) แล้ว sample CPU/RAM/IO/GPU
ของ process tree งานนี้ทุก 0.5 วิ ปริ้นลง stdout (ไปจบใน `log/`)

```bash
~/sutpct-env/bin/python3 run_with_stats.py <raw_file> -o <output.root>
```

อาร์กิวเมนต์ส่งต่อให้ข้อ 1 ตรงๆ **นี่คือตัวที่ GUI เรียกอัตโนมัติหลังจบทุกรัน**

## 3. `check_gating_consistency.py` — เช็ควินัยการ gate ฝั่ง DAQ

เทียบจำนวน event ที่บันทึกจริง (จาก `log/`) กับ 2 การทำนาย:
- gate ไม่มีผล: `trigger_freq_hz × ระยะเวลารันทั้งหมด`
- gate หยุด trigger เต็มที่: `trigger_freq_hz × ระยะเวลา OPEN รวม`

ถ้าตรงกับอันหลัง = gate ทำงาน (ไม่มี event ตอน gate ปิด)

```bash
~/sutpct-env/bin/python3 check_gating_consistency.py <run.log> <run_gating.csv> [--trigger-freq HZ]
```

| อาร์กิวเมนต์ | ความหมาย |
|---|---|
| `run_log` | `log/run*.log` (ต้องมีบรรทัด `Data events : N`) |
| `gating_csv` | `gating/run*_gating.csv` |
| `--trigger-freq` | override ค่าจาก header ของ gating csv |

⚠️ ตรวจแค่วินัยการ gate ฝั่ง DAQ **ไม่ใช่ตัวจับบีมปลิ้น** — ALPIDE มองไม่เห็นอะไรตอน ungated
อยู่แล้วไม่ว่าจะมีบีมหรือไม่

## 4. `ocr_video.py` — OCR วิดีโอ MU (ใช้ GPU)

อ่านตัวเลข MU1/MU2/rate/progress จาก `mu_video_*.mp4` (ROI 4 แถบซ้อนกัน แถบละ 80px)
ด้วย EasyOCR + validate ช่วงค่า + `_MuPairFilter` (กันค่าสะสมลด/เด้ง)

```bash
# batch: OCR ทุก mp4 ใน ../video/ ที่ยังไม่มี _ocr.csv  (โหลด EasyOCR ครั้งเดียว)
~/sutpct-env/bin/python3 ocr_video.py
~/sutpct-env/bin/python3 ocr_video.py --force            # ทำซ้ำทุกไฟล์

# ไฟล์เดียว
~/sutpct-env/bin/python3 ocr_video.py <mu_video_*.mp4> [--max-frames N]

# diagnostic: dump ภาพ ROI ดิบ (scale เท่าที่ OCR อ่าน) ไว้ดูด้วยตา
~/sutpct-env/bin/python3 ocr_video.py <mu_video_*.mp4> --save-frames 100
```

เอาต์พุตต่อวิดีโอ (ที่เดียวกับไฟล์): `<video>_ocr.csv` (per-frame + timestamp จริง)
และ `<video>_ocr.png` (กราฟ 3 แผง)

GUI **ไม่เรียกตัวนี้อัตโนมัติ** — อัดวิดีโอ + scp ขึ้น `video/` เท่านั้น ต้อง SSH มารันเอง

หมายเหตุ: mu1/mu2 มีเพดานความแม่นจาก moire + font เล็กตอนถ่ายจอ (ยืนยันด้วย `--save-frames`)
mu_rate/progress อ่านชัด — แก้ทาง software ต่อไม่ช่วย ต้องแก้ที่ hardware
